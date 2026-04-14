"""Generate SEO metadata (titles and descriptions) for translated content."""

from __future__ import annotations

import os
import json
import time
from pathlib import Path

import requests

from ..config import PipelineConfig
from ..storage import JSONLStore, ProgressTracker


OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

SEO_PROMPT = """Generate an SEO-optimized title and meta description for this content.

Title: {title}
Summary: {summary}
Language: {language}

Return as JSON:
{{"title": "SEO title (50-60 chars)", "description": "Meta description (150-160 chars)"}}

Return ONLY the JSON, no other text."""


def _generate_seo_meta(title: str, summary: str, language: str, model: str, api_key: str) -> dict:
    """Generate SEO title and description via LLM."""
    prompt = SEO_PROMPT.format(title=title, summary=summary or title, language=language)

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
            "max_tokens": 300,
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()

    # Parse JSON from response (handle markdown code blocks)
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(l for l in lines if not l.strip().startswith("```"))

    return json.loads(content)


def run(config: PipelineConfig) -> dict:
    """Generate SEO metadata for all content in translation locales."""
    print("\n  SEO Meta")
    print("  " + "─" * 38)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key and not config.dry_run:
        print("  Error: OPENROUTER_API_KEY required")
        return {"error": "no API key"}

    store = JSONLStore(config.data_dir)
    seo_path = Path(config.data_dir) / "seo-meta.json"

    # Load existing SEO data
    seo_data = {}
    if seo_path.exists():
        with open(seo_path, "r", encoding="utf-8") as f:
            seo_data = json.load(f)

    total = 0
    locales = config.translation.locales

    for locale in locales:
        from .translate import LOCALE_NAMES
        lang_name = LOCALE_NAMES.get(locale, locale)
        progress = ProgressTracker(config.data_dir, f"seo_{locale}")

        for content_type in config.content_types:
            entries = store.read(content_type, locale=locale)
            pending = [e for e in entries if not progress.is_done(e["id"])]
            print(f"  {content_type} ({locale}): {len(pending)} pending")

            if config.dry_run:
                total += len(pending)
                continue

            for entry in pending:
                title = entry.get("title") or ""
                summary = entry.get("summary") or ""

                if not title:
                    progress.mark_done(entry["id"])
                    continue

                try:
                    meta = _generate_seo_meta(title, summary, lang_name, config.seo.model, api_key)
                    entry_key = str(entry["id"])
                    seo_data.setdefault(entry_key, {})
                    seo_data[entry_key][f"title_{locale}"] = meta.get("title", "")
                    seo_data[entry_key][f"description_{locale}"] = meta.get("description", "")
                    progress.mark_done(entry["id"])
                    total += 1

                    # Save incrementally
                    with open(seo_path, "w", encoding="utf-8") as f:
                        json.dump(seo_data, f, ensure_ascii=False, indent=2)

                except Exception as e:
                    print(f"    Error for {entry['id']}: {e}")

                time.sleep(config.sleep)

    print(f"  Generated: {total} SEO entries")
    return {"generated": total}
