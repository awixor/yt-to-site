"""Generate one-sentence summaries for content items.

Summaries serve as semantic anchors for interlinking and SEO descriptions.
"""

from __future__ import annotations

import os
import sys
import time

import requests

from ..config import PipelineConfig
from ..storage import JSONLStore, ProgressTracker


OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

SUMMARY_PROMPT = """Summarize the following text in exactly ONE complex sentence (max 2 lines).

Do NOT just describe the general topic. Explicitly name specific arguments, entities,
and terminology discussed to serve as keyword anchors for future hyperlinking.

Title: {title}

Content:
{content}

Return only the summary sentence, no other text or markdown."""


def _generate_summary(content: str, title: str, model: str, api_key: str) -> str:
    """Call LLM to generate a one-sentence summary."""
    prompt = SUMMARY_PROMPT.format(title=title, content=content[:8000])

    response = requests.post(
        OPENROUTER_API,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 500,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip().strip("\"'")


def _summarize_with_retry(content: str, title: str, model: str, api_key: str, max_retries: int = 3) -> str:
    """Generate summary with exponential backoff."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return _generate_summary(content, title, model, api_key)
        except requests.exceptions.HTTPError as e:
            last_error = e
            if e.response.status_code == 429:
                time.sleep((2 ** attempt) * 5)
            else:
                raise
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep((2 ** attempt) * 2)
    raise last_error


def run(config: PipelineConfig) -> dict:
    """Generate summaries for all content items missing them."""
    print("\n  Summarize")
    print("  " + "─" * 38)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key and not config.dry_run:
        print("  Error: OPENROUTER_API_KEY required")
        return {"error": "no API key"}

    store = JSONLStore(config.data_dir)
    progress = ProgressTracker(config.data_dir, "summarize")
    total = 0

    for content_type in config.content_types:
        entries = store.read(content_type)
        pending = [e for e in entries if not e.get("summary") and not progress.is_done(e["id"])]

        print(f"  {content_type}: {len(pending)} pending")

        if config.dry_run:
            total += len(pending)
            continue

        entries_by_id = {e["id"]: e for e in entries}

        for entry in pending:
            content = entry.get("content") or entry.get("description") or ""
            title = entry.get("title") or entry.get("full_title") or ""

            # For videos, use transcript if available
            if entry.get("content_type") == "video" and not content:
                transcript = store.read_transcript(entry["id"])
                if transcript:
                    content = transcript

            if not content or len(content) < 50:
                progress.mark_done(entry["id"])
                continue

            try:
                summary = _summarize_with_retry(content, title, config.summarization.model, api_key)
                entries_by_id[entry["id"]]["summary"] = summary
                progress.mark_done(entry["id"])
                total += 1

                # Save incrementally
                store.write(content_type, list(entries_by_id.values()))

            except Exception as e:
                print(f"    Error summarizing {entry['id']}: {e}")

            time.sleep(config.sleep)

    print(f"  Generated: {total} summaries")
    return {"generated": total}
