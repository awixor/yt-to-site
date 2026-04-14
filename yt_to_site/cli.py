"""CLI entry point for yt-to-site."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .config import PipelineConfig
from .pipeline import run_pipeline


@click.group()
@click.version_option()
def main():
    """yt-to-site: Turn any YouTube channel into a multi-language content website."""
    pass


@main.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Preview what would be done without calling APIs")
@click.option("--skip", multiple=True, help="Stages to skip (youtube_sync, transcribe, summarize, translate, interlink, seo)")
@click.option("--sleep", type=float, default=None, help="Override delay between API calls")
def run(config_file: str, dry_run: bool, skip: tuple[str, ...], sleep: float | None):
    """Run the full pipeline from a config file."""
    config = PipelineConfig.from_yaml(config_file)

    if dry_run:
        config.dry_run = True
    if sleep is not None:
        config.sleep = sleep

    try:
        results = run_pipeline(config, skip=set(skip))
    except KeyboardInterrupt:
        print("\n\nInterrupted. Progress saved — run again to resume.")
        sys.exit(0)


@main.command()
@click.argument("config_file", type=click.Path(exists=True))
def init(config_file: str):
    """Initialize data directory and fetch initial video list."""
    config = PipelineConfig.from_yaml(config_file)

    from .storage import JSONLStore
    store = JSONLStore(config.data_dir)
    print(f"Data directory: {store.data_dir}")
    print(f"Transcripts: {store.transcripts_dir()}")

    # Run just the YouTube sync
    from .stages import youtube_sync
    youtube_sync.run(config)


@main.command()
@click.argument("config_file", type=click.Path(exists=True))
def status(config_file: str):
    """Show pipeline status and counts."""
    config = PipelineConfig.from_yaml(config_file)

    from .storage import JSONLStore, ProgressTracker
    store = JSONLStore(config.data_dir)

    print(f"\n  Pipeline Status")
    print(f"  {'=' * 38}")
    print(f"  Data dir: {config.data_dir}")
    print(f"  Channel: {config.channel.handle}")

    for content_type in config.content_types:
        entries = store.read(content_type)
        print(f"\n  {content_type}: {len(entries)} items")

        # Check transcripts for videos
        if content_type == "videos":
            with_transcript = sum(1 for e in entries if store.has_transcript(e["id"]))
            print(f"    Transcribed: {with_transcript}")

        # Check summaries
        with_summary = sum(1 for e in entries if e.get("summary"))
        print(f"    Summarized: {with_summary}")

        # Check translations
        for locale in config.translation.locales:
            translated = store.read(content_type, locale=locale)
            print(f"    Translated ({locale}): {len(translated)}")


if __name__ == "__main__":
    main()
