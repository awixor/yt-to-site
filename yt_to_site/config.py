"""Configuration management for yt-to-site pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ChannelConfig(BaseModel):
    """YouTube channel configuration."""

    handle: str  # e.g. "@mkbhd"
    source_language: str = "en"  # primary language of the channel


class TranscriptionConfig(BaseModel):
    """Transcription stage configuration."""

    format_model: str = "google/gemini-2.5-flash"
    parallel_workers: int = 6
    poll_interval: int = 5
    max_poll_attempts: int = 60
    quran_validation: bool = False  # enable Quran verse correction (requires quran-validator)


class TranslationConfig(BaseModel):
    """Translation stage configuration."""

    locales: list[str] = Field(default_factory=lambda: ["en"])
    model: str = "google/gemini-2.5-flash"
    fallback_model: str = "google/gemini-2.5-pro"
    batch_size: int = 20
    parallel_workers: int = 5


class SummarizationConfig(BaseModel):
    """Summarization stage configuration."""

    model: str = "google/gemini-2.5-flash"
    max_tokens: int = 500


class InterlinkConfig(BaseModel):
    """Interlinking stage configuration."""

    embed_model: str = "embed-multilingual-v3.0"
    rerank_model: str = "rerank-v3.5"
    embed_batch_size: int = 96
    min_similarity: float = 0.3
    max_links_per_chunk: int = 3


class SEOConfig(BaseModel):
    """SEO metadata generation configuration."""

    model: str = "google/gemini-2.5-flash"


class WebConfig(BaseModel):
    """Web frontend configuration."""

    site_name: str = "My Channel"
    site_description: str = ""
    default_locale: str = "en"
    supported_locales: list[str] = Field(default_factory=lambda: ["en"])
    domain: str | None = None
    analytics_id: str | None = None  # e.g. PostHog project key


class PipelineConfig(BaseModel):
    """Top-level pipeline configuration."""

    channel: ChannelConfig
    data_dir: str = "data"
    content_types: list[str] = Field(default_factory=lambda: ["videos"])
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    summarization: SummarizationConfig = Field(default_factory=SummarizationConfig)
    interlink: InterlinkConfig = Field(default_factory=InterlinkConfig)
    seo: SEOConfig = Field(default_factory=SEOConfig)
    web: WebConfig = Field(default_factory=WebConfig)

    # Global settings
    sleep: float = 1.0  # delay between API calls
    dry_run: bool = False

    @classmethod
    def from_yaml(cls, path: str | Path) -> PipelineConfig:
        """Load config from a YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineConfig:
        """Load config from a dictionary."""
        return cls(**data)
