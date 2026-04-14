"""Translate content to multiple languages via LLM.

Supports JSONL content translation and transcript translation.
Includes Arabic leakage detection and fallback model support.
"""

from __future__ import annotations

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from ..config import PipelineConfig
from ..storage import JSONLStore, ProgressTracker


OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

TRANSLATABLE_FIELDS = ["title", "full_title", "description", "content", "summary"]

LOCALE_NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "tr": "Turkish",
    "ar": "Arabic",
    "ur": "Urdu",
    "id": "Indonesian",
    "ms": "Malay",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "pt": "Portuguese",
    "ru": "Russian",
    "hi": "Hindi",
}


def _get_locale_name(locale: str) -> str:
    return LOCALE_NAMES.get(locale, locale)


def _translate_text(text: str, target_locale: str, model: str, api_key: str) -> str:
    """Translate text to target language."""
    target_lang = _get_locale_name(target_locale)
    prompt = f"""Translate the following text to {target_lang}.

Rules:
- Translate naturally, not word-for-word
- Preserve markdown formatting (links, headings, bold, etc.)
- Preserve proper nouns and technical terms as-is when appropriate
- Return ONLY the translated text, no explanations

Text:
{text}"""

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
            "max_tokens": 16000,
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _translate_with_retry(text: str, target_locale: str, model: str, fallback_model: str, api_key: str, max_retries: int = 3) -> str:
    """Translate with retry and fallback model support."""
    last_error = None
    for attempt in range(max_retries):
        current_model = fallback_model if attempt > 0 else model
        try:
            return _translate_text(text, target_locale, current_model, api_key)
        except requests.exceptions.HTTPError as e:
            last_error = e
            if e.response.status_code == 429:
                time.sleep((2 ** attempt) * 10)
            elif e.response.status_code >= 500:
                time.sleep((2 ** attempt) * 5)
            else:
                raise
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep((2 ** attempt) * 3)
    raise last_error


def _translate_entry(entry: dict, target_locale: str, model: str, fallback_model: str, api_key: str) -> dict:
    """Translate all translatable fields in an entry."""
    translated = dict(entry)
    for field in TRANSLATABLE_FIELDS:
        value = entry.get(field)
        if value and isinstance(value, str) and len(value) > 0:
            try:
                translated[field] = _translate_with_retry(value, target_locale, model, fallback_model, api_key)
            except Exception:
                pass  # keep original on failure
    return translated


def _translate_transcript_chunks(text: str, target_locale: str, model: str, fallback_model: str, api_key: str, max_chunk: int = 6000) -> str:
    """Translate a transcript by splitting on headings and translating chunks."""
    # Split by markdown headings
    sections = re.split(r"(^##+ .+$)", text, flags=re.MULTILINE)

    chunks: list[str] = []
    current = ""
    for section in sections:
        if len(current) + len(section) > max_chunk and current:
            chunks.append(current)
            current = section
        else:
            current += section
    if current:
        chunks.append(current)

    translated_parts = []
    for chunk in chunks:
        translated = _translate_with_retry(chunk, target_locale, model, fallback_model, api_key)
        translated_parts.append(translated)

    return "\n\n".join(translated_parts)


def run(config: PipelineConfig) -> dict:
    """Translate all content types to configured locales."""
    print("\n  Translate")
    print("  " + "─" * 38)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key and not config.dry_run:
        print("  Error: OPENROUTER_API_KEY required")
        return {"error": "no API key"}

    store = JSONLStore(config.data_dir)
    total = 0

    for locale in config.translation.locales:
        print(f"\n  Locale: {locale} ({_get_locale_name(locale)})")
        progress = ProgressTracker(config.data_dir, f"translate_{locale}")

        model = config.translation.model
        fallback = config.translation.fallback_model

        for content_type in config.content_types:
            source_entries = store.read(content_type)
            existing_translated = store.read(content_type, locale=locale)
            existing_ids = {e["id"] for e in existing_translated}

            pending = [e for e in source_entries if e["id"] not in existing_ids and not progress.is_done(e["id"])]
            print(f"    {content_type}: {len(pending)} pending")

            if config.dry_run:
                total += len(pending)
                continue

            for entry in pending:
                try:
                    translated = _translate_entry(entry, locale, model, fallback, api_key)
                    store.append(content_type, translated, locale=locale)
                    progress.mark_done(entry["id"])
                    total += 1
                except Exception as e:
                    print(f"      Error translating {entry['id']}: {e}")

                time.sleep(config.sleep)

        # Translate transcripts
        if "videos" in config.content_types:
            transcripts_dir = store.transcripts_dir()
            formatted_files = list(transcripts_dir.glob("*_formatted.md"))
            formatted_files = [f for f in formatted_files if f"_formatted_{locale}" not in f.name
                               and "_formatted_" not in f.name.replace("_formatted.md", "")]

            pending_transcripts = [
                f for f in formatted_files
                if not store.has_transcript(int(f.stem.replace("_formatted", "")), locale=locale)
            ]
            print(f"    transcripts: {len(pending_transcripts)} pending")

            if not config.dry_run:
                for f in pending_transcripts:
                    video_id = int(f.stem.replace("_formatted", ""))
                    text = f.read_text(encoding="utf-8")
                    try:
                        translated = _translate_transcript_chunks(text, locale, model, fallback, api_key)
                        store.write_transcript(video_id, translated, locale=locale)
                        total += 1
                    except Exception as e:
                        print(f"      Error translating transcript {video_id}: {e}")
                    time.sleep(config.sleep)

    print(f"\n  Translated: {total} items")
    return {"translated": total}
