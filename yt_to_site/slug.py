"""URL slug generation.

Must stay in sync with web/lib/slug.ts — if you change the algorithm here,
update the TypeScript version too.
"""

from __future__ import annotations

import re
import unicodedata


def generate_slug(text: str, max_length: int = 50) -> str:
    """Generate a URL-safe slug from text.

    Algorithm:
    1. Truncate to max_length chars
    2. Lowercase and trim
    3. Normalize unicode (strip diacritics for Latin scripts)
    4. Keep only alphanumeric, spaces, and hyphens
    5. Replace spaces with hyphens
    6. Collapse multiple hyphens
    7. Remove trailing hyphen
    """
    if not text:
        return ""

    slug = text[:max_length + 1]
    slug = slug.lower().strip()

    # Normalize: decompose then remove combining marks (diacritics)
    slug = unicodedata.normalize("NFD", slug)
    slug = re.sub(r"[\u0300-\u036f]", "", slug)  # Latin combining diacritics

    # Keep alphanumeric (any script), spaces, hyphens
    slug = re.sub(r"[^\w\s-]", "", slug)

    # Replace whitespace with hyphens
    slug = re.sub(r"\s+", "-", slug)

    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)

    # Remove trailing hyphen
    slug = slug.rstrip("-")

    return slug


def slugify_heading(text: str) -> str:
    """Generate an anchor ID from a heading for TOC links."""
    slug = unicodedata.normalize("NFD", text)
    slug = re.sub(r"[\u0300-\u036f\u064B-\u065F\u0670]", "", slug)
    slug = slug.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "heading"
