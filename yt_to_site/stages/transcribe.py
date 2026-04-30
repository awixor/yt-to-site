"""Transcribe YouTube videos and format into structured markdown.

Two-phase process:
1. Raw transcription via ClipScript API (polls until transcript is ready)
2. Formatting into structured markdown with headings via LLM

Optional: Quran verse validation (requires `quran-validator` package).
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


CLIPSCRIPT_API = "https://clipscript.uk/api/v1/transcriptions"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

# Polling configuration for ClipScript
POLL_INTERVAL = 10  # seconds
MAX_POLL_ATTEMPTS = 120  # 20min max wait (yt-dlp download + transcription can be slow)

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

# Quran validation support (optional)
_quran_validator = None
_quran_system_prompt = ""


def _init_quran_validation():
    """Try to load quran-validator for optional Quran verse correction."""
    global _quran_validator, _quran_system_prompt
    if _quran_validator is not None:
        return True
    try:
        from quran_validator import QuranValidator, normalize_arabic, SYSTEM_PROMPTS
        _quran_validator = QuranValidator()
        _quran_system_prompt = SYSTEM_PROMPTS.get("xml", "")
        return True
    except ImportError:
        return False


def _fix_tagged_verses(text: str) -> str:
    """Replace LLM-tagged <quran ref="S:A">...</quran> with authentic Uthmani text.

    Requires the `quran-validator` package. If not installed, strips tags only.
    """
    if not _init_quran_validation():
        return re.sub(r"</?quran[^>]*>", "", text)

    from quran_validator import normalize_arabic

    pattern = re.compile(r'<quran\s+ref="(\d+):(\d+)(?:-(\d+))?"\s*>(.*?)</quran>', re.DOTALL)

    def _align_partial(quote: str, full_verse: str) -> str | None:
        n_quote = normalize_arabic(quote).split()
        full_words = full_verse.split()
        n_full = [normalize_arabic(w) for w in full_words]
        if not n_quote or len(n_quote) > len(n_full):
            return None
        for i in range(len(n_full) - len(n_quote) + 1):
            if all(n_full[i + j] == n_quote[j] for j in range(len(n_quote))):
                return " ".join(full_words[i:i + len(n_quote)])
        return None

    def _preserve_brackets(original: str, corrected: str) -> str:
        has_open = original.startswith("﴿")
        has_close = original.endswith("﴾")
        result = re.sub(r"^﴿\s*", "", corrected)
        result = re.sub(r"\s*﴾$", "", result)
        if has_open:
            result = f"﴿{result}"
        if has_close:
            result = f"{result}﴾"
        return result

    def replace_match(m):
        surah = int(m.group(1))
        start_ayah = int(m.group(2))
        end_ayah = int(m.group(3)) if m.group(3) else None
        original_text = m.group(4).strip()

        if end_ayah:
            parts = []
            for ayah in range(start_ayah, end_ayah + 1):
                verse = _quran_validator.get_verse(surah, ayah)
                if verse:
                    parts.append(verse.text)
            if parts:
                return " ۝ ".join(parts)
        else:
            verse = _quran_validator.get_verse(surah, start_ayah)
            if verse:
                aligned = _align_partial(original_text, verse.text)
                if aligned:
                    return _preserve_brackets(original_text, aligned)
                if len(original_text) / max(len(verse.text), 1) > 0.4:
                    return _preserve_brackets(original_text, verse.text)

        return original_text

    result = pattern.sub(replace_match, text)
    result = re.sub(r"</?quran[^>]*>", "", result)
    return result


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


def _get_format_system_prompt(config: PipelineConfig) -> str:
    """Build the formatting system prompt, optionally including Quran tagging instructions."""
    prompt = FORMAT_SYSTEM_PROMPT
    if config.transcription.quran_validation and _init_quran_validation():
        prompt += "\n\n" + _quran_system_prompt
    return prompt


def format_transcript(raw_transcript: str, video_title: str, model: str, api_key: str, config: PipelineConfig) -> str:
    """Format raw transcript to structured markdown via LLM with continuation support."""
    system_prompt = _get_format_system_prompt(config)
    messages = [
        {"role": "system", "content": system_prompt},
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

    result = "\n\n".join(parts)

    # Validate and fix Quran verses if enabled
    if config.transcription.quran_validation:
        try:
            result = _fix_tagged_verses(result)
        except Exception:
            result = re.sub(r"</?quran[^>]*>", "", result)

    return result


# -------------------- CLIPSCRIPT TRANSCRIPTION --------------------
def _transcribe_via_clipscript(youtube_id: str, api_key: str, language: str = "en") -> str:
    """Call ClipScript API and poll until transcript is ready."""
    youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"

    # 1. Start transcription job (POST)
    response = requests.post(
        CLIPSCRIPT_API,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "url": youtube_url,
            "language": language,
        },
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()

    if "error" in result:
        raise ValueError(result["error"])

    # If it's already complete (cached), return immediately
    if result.get("status") == "complete":
        return result["transcript"]

    job_id = result.get("id")
    if not job_id:
        raise ValueError(f"Unexpected response (no job ID): {result}")

    # 2. Poll until complete (GET)
    for attempt in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL)
        
        response = requests.get(
            f"{CLIPSCRIPT_API}/{job_id}",
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

        if "error" in result:
            raise ValueError(result["error"])
        if result.get("status") == "complete":
            return result["transcript"]
        if result.get("status") == "failed":
            raise ValueError(f"Transcription failed for job {job_id}")

    raise TimeoutError(f"Transcript not ready after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s")


def _transcribe_with_retry(youtube_id: str, api_key: str, language: str = "en", max_retries: int = 3) -> str:
    """Transcribe via ClipScript with exponential backoff."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return _transcribe_via_clipscript(youtube_id, api_key, language)
        except requests.exceptions.HTTPError as e:
            last_error = e
            if e.response.status_code == 429:
                time.sleep((2 ** attempt) * 10)
            elif e.response.status_code >= 500:
                time.sleep((2 ** attempt) * 5)
            else:
                raise
        except requests.exceptions.Timeout as e:
            last_error = e
            time.sleep((2 ** attempt) * 5)
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep((2 ** attempt) * 3)

    raise last_error


def _process_video(video: dict, config: PipelineConfig, store: JSONLStore, progress: ProgressTracker) -> dict:
    """Process a single video: transcribe via ClipScript and format via LLM."""
    video_id = video["id"]
    youtube_id = video.get("youtube_id", "")
    title = video.get("title") or video.get("full_title") or f"Video {video_id}"

    if not youtube_id:
        return {"skipped": True}

    clean_yt_id = youtube_id.split("?")[0]
    clipscript_key = os.getenv("CLIPSCRIPT_API_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")

    if not clipscript_key:
        return {"error": "CLIPSCRIPT_API_KEY not set"}
    if not openrouter_key:
        return {"error": "OPENROUTER_API_KEY not set"}

    result = {"video_id": video_id, "youtube_id": clean_yt_id}

    # Step 1: Raw transcript via ClipScript
    if not store.has_transcript(video_id, formatted=False):
        try:
            raw = _transcribe_with_retry(clean_yt_id, clipscript_key, config.channel.source_language)
            store.write_transcript(video_id, raw, formatted=False)
            result["transcribed"] = True
            time.sleep(config.sleep)
        except Exception as e:
            result["error"] = str(e)
            return result

    # Step 2: Format via LLM
    if not store.has_transcript(video_id, formatted=True):
        try:
            raw = store.read_transcript(video_id, formatted=False)
            formatted = format_transcript(raw, title, config.transcription.format_model, openrouter_key, config)
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

    # Check for Quran validation
    if config.transcription.quran_validation:
        if _init_quran_validation():
            print("  Quran validation: enabled")
        else:
            print("  Quran validation: quran-validator not installed, skipping")

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
