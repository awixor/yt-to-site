"""Pipeline orchestrator — runs stages in sequence with skip controls."""

from __future__ import annotations

from .config import PipelineConfig
from .stages import youtube_sync, transcribe, summarize, translate, interlink, seo


STAGES = [
    ("youtube_sync", youtube_sync),
    ("transcribe", transcribe),
    ("summarize", summarize),
    ("translate", translate),
    ("interlink", interlink),
    ("seo", seo),
]


def run_pipeline(config: PipelineConfig, skip: set[str] | None = None) -> dict:
    """Run the full pipeline with optional stage skipping.

    Args:
        config: Pipeline configuration
        skip: Set of stage names to skip (e.g. {"translate", "interlink"})

    Returns:
        Dict of stage results
    """
    skip = skip or set()
    results = {}

    print("\n  PIPELINE")
    print("  " + "=" * 38)

    if config.dry_run:
        print("  Mode: DRY RUN")

    for name, module in STAGES:
        if name in skip:
            print(f"\n  Skipped: {name}")
            results[name] = {"skipped": True}
            continue

        try:
            results[name] = module.run(config)
        except KeyboardInterrupt:
            print(f"\n\n  Interrupted during {name}. Progress saved.")
            results[name] = {"interrupted": True}
            break
        except Exception as e:
            print(f"\n  Error in {name}: {e}")
            results[name] = {"error": str(e)}

    print("\n  " + "=" * 38)
    print("  Pipeline complete")

    return results
