"""Fetch video metadata from a YouTube channel.

Uses YouTube Data API v3 to get all videos from a channel's uploads playlist.
New videos are appended to the JSONL store with auto-incrementing IDs.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from ..config import PipelineConfig
from ..storage import JSONLStore


COUNTER_FILE = "youtube_id_counter.json"
ID_START = 100_000


def _load_counter(data_dir: Path) -> int:
    """Load the persistent ID counter."""
    counter_path = data_dir / COUNTER_FILE
    if counter_path.exists():
        try:
            with open(counter_path, "r") as f:
                return json.load(f).get("next_id", ID_START)
        except (json.JSONDecodeError, KeyError):
            pass
    return ID_START


def _save_counter(data_dir: Path, next_id: int) -> None:
    """Persist the ID counter."""
    counter_path = data_dir / COUNTER_FILE
    with open(counter_path, "w") as f:
        json.dump({"next_id": next_id}, f)


def fetch_channel_videos(channel_handle: str, api_key: str) -> list[dict]:
    """Fetch all videos from a YouTube channel."""
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", developerKey=api_key)

    # Get channel's uploads playlist
    ch_resp = youtube.channels().list(
        forHandle=channel_handle,
        part="contentDetails"
    ).execute()

    items = ch_resp.get("items", [])
    if not items:
        print(f"  Could not find channel for {channel_handle}", file=sys.stderr)
        return []

    uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"  Uploads playlist: {uploads_playlist_id}")

    videos = []
    next_page = None
    while True:
        pl_resp = youtube.playlistItems().list(
            playlistId=uploads_playlist_id,
            part="snippet",
            maxResults=50,
            pageToken=next_page
        ).execute()

        for item in pl_resp.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue
            videos.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "thumbnails": snippet.get("thumbnails", {}),
            })

        next_page = pl_resp.get("nextPageToken")
        if not next_page:
            break

    return videos


def map_to_schema(yt_item: dict, item_id: int, source_language: str) -> dict:
    """Map YouTube API item to the content schema."""
    published = yt_item["published_at"].replace("Z", "")
    thumb = yt_item.get("thumbnails", {})
    thumb_url = (thumb.get("maxres") or thumb.get("high") or thumb.get("medium") or {}).get("url")

    return {
        "id": item_id,
        "title": yt_item["title"],
        "full_title": yt_item["title"],
        "description": yt_item["description"] or None,
        "content": None,
        "content_type": "video",
        "youtube_id": yt_item["video_id"],
        "thumbnail_url": thumb_url,
        "is_series": False,
        "is_active": True,
        "parent_id": None,
        "authored_date": published,
        "summary": None,
        "source_language": source_language,
        "source": "youtube",
    }


def run(config: PipelineConfig) -> dict:
    """Sync videos from YouTube channel into the JSONL store."""
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("\n  Skipped (no YOUTUBE_API_KEY)")
        return {"skipped": True}

    print("\n  YouTube channel sync")
    print("  " + "─" * 38)

    store = JSONLStore(config.data_dir)
    data_dir = Path(config.data_dir)

    # Get existing YouTube IDs from all video files
    existing_yt_ids: set[str] = set()
    for entry in store.stream("videos"):
        yt_id = entry.get("youtube_id")
        if yt_id:
            existing_yt_ids.add(yt_id.split("?")[0])
    for entry in store.stream("videos", series=True):
        yt_id = entry.get("youtube_id")
        if yt_id:
            existing_yt_ids.add(yt_id.split("?")[0])

    print(f"  Existing videos: {len(existing_yt_ids)}")

    # Fetch from YouTube
    try:
        channel_videos = fetch_channel_videos(config.channel.handle, api_key)
    except Exception as e:
        print(f"  YouTube API error: {e}", file=sys.stderr)
        return {"error": str(e)}

    print(f"  Videos on channel: {len(channel_videos)}")

    # Filter new only
    new_videos = [v for v in channel_videos if v["video_id"] not in existing_yt_ids]
    print(f"  New videos: {len(new_videos)}")

    if not new_videos:
        print("  Nothing to import.")
        return {"imported": 0}

    if config.dry_run:
        for v in new_videos[:10]:
            print(f"    - {v['title'][:60]} ({v['video_id']})")
        if len(new_videos) > 10:
            print(f"    ... and {len(new_videos) - 10} more")
        return {"would_import": len(new_videos)}

    # Assign IDs and append
    next_id = _load_counter(data_dir)
    count = 0
    for yt_item in new_videos:
        entry = map_to_schema(yt_item, next_id, config.channel.source_language)
        store.append("videos", entry)
        print(f"  + [{next_id}] {yt_item['title'][:60]}")
        next_id += 1
        count += 1

    _save_counter(data_dir, next_id)
    print(f"\n  Imported {count} videos (IDs {next_id - count}–{next_id - 1})")
    return {"imported": count}
