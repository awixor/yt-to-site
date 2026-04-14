"""Transcribe YouTube videos and format into structured markdown.

Two-phase process:
1. Raw transcription via configurable provider (OpenRouter, etc.)
2. Formatting into markdown with headings via LLM
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from ..config import PipelineConfig
from ..storage import JSONLStore, ProgressTracker


OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

FORMAT_SYSTEM_PROMPT = """You are a professional transcription editor.

Your task is to format a raw transcript into clean, readable markdown:

1. Add chapter headings (## and ###) to structure content by topic transitions
2. Break text into logical paragraphs for readability
3. Fix obvious transcription mistakes while preserving meaning
4. Keep everything in the original language — do not translate
5. Format in clean markdown

CONTINUATION RULES:
- If the response would be too long, add "[continue]" at the end
- When continuing, start exactly where you left off — do not repeat content
"""


def _call_openrouter(messages: list[dict], model: str, api_key: str, max_tokens: int = 16000) -> str:
    """Make an OpenRouter API call and return the response content."""
    response = requests.post(
        OPENROUTER_API,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens,
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _clean_formatted_content(text: str) -> str:
    """Clean LLM formatting artifacts from transcript."""
    content = text.strip()

    # Remove markdown code blocks
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    # Remove planning tags
    if "</formatting_plan>" in content:
        parts = content.split("</formatting_plan>")
        content = parts[-1].strip()

    # Remove continue markers
    content = content.replace("[continue]", "").replace("[Continue]", "").strip()

    return content


def format_transcript(raw_transcript: str, video_title: str, model: str, api_key: str) -> str:
    """Format raw transcript to structured markdown via LLM with continuation support."""
    messages = [
        {"role": "system", "content": FORMAT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Video title: {video_title}\n\nRaw transcript:\n{raw_transcript}"},
    ]

    parts = []
    for _ in range(10):  # safety limit
        content = _call_openrouter(messages, model, api_key)
        has_continue = "[continue]" in content.lower()

        cleaned = _clean_formatted_content(content)
        if cleaned:
            parts.append(cleaned)

        if has_continue:
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Please continue from where you left off."})
            if len(messages) > 12:
                messages = messages[:2] + messages[-8:]
        else:
            break

    return "\n\n".join(parts)


def _transcribe_with_retry(youtube_id: str, model: str, api_key: str, max_retries: int = 3) -> str:
    """Transcribe a video with exponential backoff."""
    # Use OpenRouter with a transcription-capable model
    messages = [
        {"role": "system", "content": "Transcribe the following YouTube video accurately. Return only the transcript text."},
        {"role": "user", "content": f"Please transcribe this YouTube video: https://www.youtube.com/watch?v={youtube_id}"},
    ]

    last_error = None
    for attempt in range(max_retries):
        try:
            return _call_openrouter(messages, model, api_key)
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


def _process_video(video: dict, config: PipelineConfig, store: JSONLStore, progress: ProgressTracker) -> dict:
    """Process a single video: transcribe and format."""
    video_id = video["id"]
    youtube_id = video.get("youtube_id", "")
    title = video.get("title") or video.get("full_title") or f"Video {video_id}"

    if not youtube_id:
        return {"skipped": True}

    clean_yt_id = youtube_id.split("?")[0]
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {"error": "OPENROUTER_API_KEY not set"}

    result = {"video_id": video_id, "youtube_id": clean_yt_id}

    # Step 1: Raw transcript
    if not store.has_transcript(video_id, formatted=False):
        try:
            raw = _transcribe_with_retry(clean_yt_id, config.transcription.model, api_key)
            store.write_transcript(video_id, raw, formatted=False)
            result["transcribed"] = True
            time.sleep(config.sleep)
        except Exception as e:
            result["error"] = str(e)
            return result

    # Step 2: Format
    if not store.has_transcript(video_id, formatted=True):
        try:
            raw = store.read_transcript(video_id, formatted=False)
            formatted = format_transcript(raw, title, config.transcription.format_model, api_key)
            store.write_transcript(video_id, formatted, formatted=True)
            result["formatted"] = True
            time.sleep(config.sleep)
        except Exception as e:
            result["error"] = str(e)
            return result

    progress.mark_done(video_id)
    return result


def run(config: PipelineConfig) -> dict:
    """Run transcription stage on all videos missing transcripts."""
    print("\n  Transcribe")
    print("  " + "─" * 38)

    store = JSONLStore(config.data_dir)
    progress = ProgressTracker(config.data_dir, "transcribe")

    # Collect videos needing transcription
    videos = [v for v in store.stream("videos") if v.get("youtube_id") and not progress.is_done(v["id"])]
    print(f"  Pending: {len(videos)} videos")

    if config.dry_run:
        for v in videos[:10]:
            yt_id = v.get("youtube_id", "")[:11]
            title = (v.get("title") or "")[:40]
            print(f"    {yt_id} | {title}")
        return {"pending": len(videos)}

    if not videos:
        return {"processed": 0}

    workers = config.transcription.parallel_workers
    processed = 0

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_video, v, config, store, progress): v for v in videos}
            for future in as_completed(futures):
                result = future.result()
                if not result.get("error"):
                    processed += 1
                else:
                    print(f"    Error: {result.get('youtube_id')}: {result['error']}")
    else:
        for video in videos:
            result = _process_video(video, config, store, progress)
            if not result.get("error"):
                processed += 1

    print(f"  Processed: {processed}/{len(videos)}")
    return {"processed": processed}
