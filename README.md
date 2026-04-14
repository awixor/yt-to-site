# yt-to-site

Turn any YouTube channel into a multi-language content website.

Point it at a channel handle, configure your target languages, and get a full pipeline that:

1. **Syncs** video metadata from YouTube
2. **Transcribes** videos via [ClipScript](https://clipscript.uk) and formats into structured markdown
3. **Summarizes** content for SEO and interlinking
4. **Translates** to multiple languages
5. **Interlinks** content with semantic hyperlinks
6. **Generates SEO** metadata per locale

Output is a static Next.js site reading from JSONL files — no database required.

## Quick Start

```bash
# Install
pip install -e .

# Configure
cp config.example.yaml config.yaml
cp .env.example .env
# Edit config.yaml with your channel handle and languages
# Add API keys to .env

# Initialize — fetch video list
yts init config.yaml

# Run full pipeline
yts run config.yaml

# Check status
yts status config.yaml

# Run with options
yts run config.yaml --dry-run
yts run config.yaml --skip transcribe --skip interlink
```

## Configuration

See `config.example.yaml` for all options. Key settings:

| Setting | Description |
|---------|-------------|
| `channel.handle` | YouTube channel handle (e.g. `@mkbhd`) |
| `channel.source_language` | Primary language of the channel |
| `translation.locales` | Target languages to translate into |
| `content_types` | What to process (default: `["videos"]`) |

## API Keys

Add to `.env`:

| Key | Used For | Required |
|-----|----------|----------|
| `YOUTUBE_API_KEY` | Fetching channel videos | Yes |
| `CLIPSCRIPT_API_KEY` | Video transcription via [ClipScript](https://clipscript.uk) | Yes |
| `OPENROUTER_API_KEY` | Transcript formatting, translation, summarization, SEO | Yes |
| `COHERE_API_KEY` | Semantic embeddings for interlinking | For interlink stage |

## Web Frontend

```bash
cd web
npm install
npm run dev
```

The Next.js app reads directly from the `data/` directory (JSONL files + transcripts). Customize the components and pages for your channel's branding.

## Architecture

```
YouTube API → youtube_sync → data/videos.jsonl
                                ↓
  ClipScript → transcribe  → data/transcripts/*.md
                                ↓
             summarize     → summary field in JSONL
                                ↓
             translate     → data/videos_en.jsonl, videos_fr.jsonl, ...
                                ↓
             interlink     → markdown links inserted into content
                                ↓
             seo           → data/seo-meta.json
                                ↓
             Next.js       → Static site from JSONL data
```

## Pipeline Stages

Each stage is **resumable** — it tracks processed IDs and skips already-done items. Run the pipeline again to pick up where it left off.

| Stage | What it does |
|-------|-------------|
| `youtube_sync` | Fetches video metadata from YouTube Data API |
| `transcribe` | Transcribes videos via ClipScript, formats into markdown (parallel) |
| `summarize` | Generates one-sentence summaries for SEO anchoring |
| `translate` | Translates content + transcripts to target locales |
| `interlink` | Embeds content, finds related items, inserts markdown links |
| `seo` | Generates SEO titles and descriptions per locale |

## Data Storage

All data lives in JSONL files (one JSON object per line):

```
data/
├── videos.jsonl              # Source language video metadata
├── videos_en.jsonl           # English translations
├── videos_fr.jsonl           # French translations
├── transcripts/
│   ├── 100000.md             # Raw transcript
│   ├── 100000_formatted.md   # Formatted markdown
│   ├── 100000_formatted_en.md
│   └── 100000_formatted_fr.md
├── link_index.json           # Semantic link index
├── seo-meta.json             # SEO metadata
└── *_progress.json           # Resumption tracking
```

## Quran Validation (Optional)

For Islamic content channels, the transcription stage can validate and correct Quran verses using authentic Uthmani text. Enable it in your config:

```yaml
transcription:
  quran_validation: true
```

This requires the [`quran-validator`](https://pypi.org/project/quran-validator/) package:

```bash
pip install quran-validator
```

When enabled, the LLM tags Quran verses during formatting, and the pipeline replaces them with verified text from the bundled Quran database.

## License

MIT
