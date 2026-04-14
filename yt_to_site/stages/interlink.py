"""Add semantic hyperlinks between content items.

Three phases:
1. Build link index (all content with summaries → URLs)
2. Embed and search for related content per chunk
3. Insert markdown links into text
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests

from ..config import PipelineConfig
from ..storage import JSONLStore, ProgressTracker
from ..slug import generate_slug


OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"


def _get_cohere_client():
    """Lazy-load Cohere client."""
    import cohere
    api_key = os.getenv("COHERE_API_KEY")
    if not api_key:
        raise ValueError("COHERE_API_KEY required for interlinking")
    return cohere.ClientV2(api_key)


def build_link_index(config: PipelineConfig) -> dict:
    """Build an index of all linkable content with summaries and URLs."""
    store = JSONLStore(config.data_dir)
    index = {"version": "1.0", "locales": {}}

    locales = [config.channel.source_language] + config.translation.locales
    default_locale = config.channel.source_language

    for locale in locales:
        entries = []
        for content_type in config.content_types:
            items = store.read(content_type, locale=locale if locale != default_locale else None)
            for item in items:
                summary = item.get("summary")
                if not summary:
                    continue
                title = item.get("title") or item.get("full_title") or ""
                slug = generate_slug(title)
                url_prefix = f"/{locale}" if locale != default_locale else ""
                url = f"{url_prefix}/{content_type}/{slug}"

                entries.append({
                    "id": item["id"],
                    "type": content_type,
                    "slug": slug,
                    "url": url,
                    "title": title,
                    "summary": summary,
                })
        index["locales"][locale] = entries

    # Save index
    index_path = Path(config.data_dir) / "link_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    return index


def _embed_texts(texts: list[str], batch_size: int = 96) -> np.ndarray:
    """Embed texts using Cohere multilingual model."""
    co = _get_cohere_client()
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = co.embed(
            texts=batch,
            model="embed-multilingual-v3.0",
            input_type="search_document",
            embedding_types=["float"],
        )
        all_embeddings.extend(response.embeddings.float_)

    return np.array(all_embeddings)


def _find_related(query_text: str, index_entries: list[dict], index_embeddings: np.ndarray, top_k: int = 5, exclude_id: int | None = None) -> list[dict]:
    """Find related content using semantic search."""
    co = _get_cohere_client()

    # Embed query
    query_resp = co.embed(
        texts=[query_text],
        model="embed-multilingual-v3.0",
        input_type="search_query",
        embedding_types=["float"],
    )
    query_embedding = np.array(query_resp.embeddings.float_[0])

    # Cosine similarity
    similarities = np.dot(index_embeddings, query_embedding) / (
        np.linalg.norm(index_embeddings, axis=1) * np.linalg.norm(query_embedding)
    )

    # Get top candidates
    top_indices = np.argsort(similarities)[::-1][:top_k * 2]

    results = []
    for idx in top_indices:
        entry = index_entries[idx]
        if exclude_id and entry["id"] == exclude_id:
            continue
        results.append({**entry, "score": float(similarities[idx])})
        if len(results) >= top_k:
            break

    return results


def _insert_links_via_llm(text_chunk: str, related: list[dict], model: str, api_key: str) -> str:
    """Use LLM to insert markdown links into text at natural anchor points."""
    if not related:
        return text_chunk

    links_desc = "\n".join(
        f"- [{r['title']}]({r['url']}) — {r['summary'][:100]}"
        for r in related[:5]
    )

    prompt = f"""Insert contextual markdown hyperlinks into the following text.

Available links to insert (only use ones that are genuinely relevant):
{links_desc}

Rules:
- Insert links at natural anchor phrases in the text
- Use markdown format: [anchor text](url)
- Do NOT add links that aren't relevant to the surrounding context
- Do NOT modify the text content — only add link markup
- Maximum 3 links per chunk
- Return the full text with links inserted

Text:
{text_chunk}"""

    response = requests.post(
        OPENROUTER_API,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 16000,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def run(config: PipelineConfig) -> dict:
    """Run interlinking: build index, embed, and insert links."""
    print("\n  Interlink")
    print("  " + "─" * 38)

    api_key = os.getenv("OPENROUTER_API_KEY")
    cohere_key = os.getenv("COHERE_API_KEY")
    if (not api_key or not cohere_key) and not config.dry_run:
        print("  Error: OPENROUTER_API_KEY and COHERE_API_KEY required")
        return {"error": "missing API keys"}

    store = JSONLStore(config.data_dir)
    progress = ProgressTracker(config.data_dir, "interlink")

    # Phase 1: Build index
    print("  Building link index...")
    index = build_link_index(config)
    default_locale = config.channel.source_language
    locale_entries = index["locales"].get(default_locale, [])
    print(f"  Index: {len(locale_entries)} linkable items")

    if config.dry_run or len(locale_entries) < 2:
        return {"index_size": len(locale_entries)}

    # Phase 2: Embed all summaries
    print("  Embedding summaries...")
    summaries = [e["summary"] for e in locale_entries]
    embeddings = _embed_texts(summaries, config.interlink.embed_batch_size)

    # Save embeddings
    np.savez_compressed(
        Path(config.data_dir) / "link_index_embeddings.npz",
        embeddings=embeddings,
    )

    # Phase 3: Process content
    total_linked = 0
    model = config.interlink.rerank_model if hasattr(config.interlink, 'rerank_model') else "google/gemini-2.5-flash"
    # Use the SEO model for link insertion LLM calls
    llm_model = config.seo.model

    for content_type in config.content_types:
        entries = store.read(content_type)
        pending = [e for e in entries if not progress.is_done(e["id"])]
        print(f"  {content_type}: {len(pending)} to process")

        entries_by_id = {e["id"]: e for e in entries}

        for entry in pending:
            content = entry.get("content") or ""
            if not content or len(content) < 100:
                # Try transcript for videos
                if entry.get("content_type") == "video":
                    content = store.read_transcript(entry["id"]) or ""
                if not content:
                    progress.mark_done(entry["id"])
                    continue

            # Split into chunks (~1000 chars)
            chunks = [content[i:i+1000] for i in range(0, len(content), 1000)]
            linked_chunks = []

            for chunk in chunks:
                related = _find_related(chunk, locale_entries, embeddings, top_k=5, exclude_id=entry["id"])
                relevant = [r for r in related if r["score"] >= config.interlink.min_similarity]

                if relevant:
                    linked_chunk = _insert_links_via_llm(chunk, relevant, llm_model, api_key)
                    linked_chunks.append(linked_chunk)
                else:
                    linked_chunks.append(chunk)

                time.sleep(config.sleep)

            # Update entry
            entries_by_id[entry["id"]]["content"] = "".join(linked_chunks)
            progress.mark_done(entry["id"])
            total_linked += 1

        # Save
        store.write(content_type, list(entries_by_id.values()))

    print(f"  Linked: {total_linked} items")
    return {"linked": total_linked}
