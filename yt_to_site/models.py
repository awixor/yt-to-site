"""Data models for yt-to-site content items."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ContentItem(BaseModel):
    """A single content item (video, article, etc.)."""

    id: int
    title: str
    full_title: str | None = None
    description: str | None = None
    content: str | None = None  # article body or transcript text
    content_type: str = "video"  # video, article, etc.
    youtube_id: str | None = None
    thumbnail_url: str | None = None
    is_series: bool = False
    is_active: bool = True
    parent_id: int | None = None  # for series episodes
    episode_number: int | None = None
    authored_date: datetime | None = None
    summary: str | None = None
    source_language: str = "en"

    # Translation fields: {locale: translated_title}
    translations: dict[str, ContentTranslation] = Field(default_factory=dict)

    # Interlinking: list of (anchor_text, url) pairs inserted into content
    links: list[tuple[str, str]] = Field(default_factory=dict)

    # SEO metadata per locale
    seo: dict[str, SEOMeta] = Field(default_factory=dict)

    # Arbitrary extra fields from source
    extra: dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ContentTranslation(BaseModel):
    """Translated fields for a content item in a specific locale."""

    locale: str
    title: str | None = None
    full_title: str | None = None
    description: str | None = None
    content: str | None = None
    summary: str | None = None


class SEOMeta(BaseModel):
    """SEO metadata for a content item in a specific locale."""

    title: str | None = None
    description: str | None = None


class SeriesItem(BaseModel):
    """A series (collection of related content items)."""

    id: int
    title: str
    slug: str | None = None
    children: list[ContentItem] = Field(default_factory=list)
