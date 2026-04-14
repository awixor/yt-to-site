"""JSONL-based storage layer for content items.

All data is stored as JSONL (one JSON object per line) — no database required.
Files are resumable, version-controllable, and streamable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator


class JSONLStore:
    """Read/write JSONL files with caching and deduplication."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, content_type: str, locale: str | None = None, series: bool = False) -> Path:
        """Get file path for a content type and locale.

        Examples:
            path_for("videos") -> data/videos.jsonl
            path_for("videos", locale="en") -> data/videos_en.jsonl
            path_for("videos", series=True) -> data/videos_series.jsonl
        """
        parts = [content_type]
        if series:
            parts.append("series")
        if locale and locale != "auto":
            parts.append(locale)
        return self.data_dir / f"{'_'.join(parts)}.jsonl"

    def read(self, content_type: str, locale: str | None = None, series: bool = False) -> list[dict]:
        """Load all entries from a JSONL file."""
        path = self.path_for(content_type, locale, series)
        if not path.exists():
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def write(self, content_type: str, entries: list[dict], locale: str | None = None, series: bool = False) -> Path:
        """Write all entries to a JSONL file (overwrites)."""
        path = self.path_for(content_type, locale, series)
        with open(path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path

    def append(self, content_type: str, entry: dict, locale: str | None = None, series: bool = False) -> None:
        """Append a single entry to a JSONL file."""
        path = self.path_for(content_type, locale, series)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def stream(self, content_type: str, locale: str | None = None, series: bool = False) -> Iterator[dict]:
        """Stream entries one at a time (memory-efficient for large files)."""
        path = self.path_for(content_type, locale, series)
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def get_ids(self, content_type: str, locale: str | None = None, series: bool = False) -> set[int]:
        """Get all IDs from a JSONL file."""
        ids = set()
        for entry in self.stream(content_type, locale, series):
            entry_id = entry.get("id")
            if entry_id is not None:
                ids.add(int(entry_id))
        return ids

    def transcripts_dir(self) -> Path:
        """Get path to transcripts directory."""
        d = self.data_dir / "transcripts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def has_transcript(self, video_id: int, locale: str | None = None, formatted: bool = True) -> bool:
        """Check if a transcript exists for a video."""
        suffix = "_formatted" if formatted else ""
        locale_suffix = f"_{locale}" if locale else ""
        path = self.transcripts_dir() / f"{video_id}{suffix}{locale_suffix}.md"
        return path.exists()

    def read_transcript(self, video_id: int, locale: str | None = None, formatted: bool = True) -> str | None:
        """Read a transcript file."""
        suffix = "_formatted" if formatted else ""
        locale_suffix = f"_{locale}" if locale else ""
        path = self.transcripts_dir() / f"{video_id}{suffix}{locale_suffix}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write_transcript(self, video_id: int, text: str, locale: str | None = None, formatted: bool = True) -> Path:
        """Write a transcript file."""
        suffix = "_formatted" if formatted else ""
        locale_suffix = f"_{locale}" if locale else ""
        path = self.transcripts_dir() / f"{video_id}{suffix}{locale_suffix}.md"
        path.write_text(text, encoding="utf-8")
        return path


class ProgressTracker:
    """Track processed IDs to enable resumable pipelines."""

    def __init__(self, data_dir: str | Path, name: str):
        self.path = Path(data_dir) / f"{name}_progress.json"
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        if self.path.exists():
            with open(self.path, "r") as f:
                self._data = json.load(f)
        else:
            self._data = {"processed": []}
        return self._data

    def _save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)

    @property
    def processed_ids(self) -> set:
        return set(self._load()["processed"])

    def mark_done(self, item_id: int | str) -> None:
        data = self._load()
        if item_id not in data["processed"]:
            data["processed"].append(item_id)
            self._save()

    def is_done(self, item_id: int | str) -> bool:
        return item_id in self.processed_ids

    def reset(self) -> None:
        self._data = {"processed": []}
        self._save()
