# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ttv-scribe** is a Twitch VOD transcription pipeline with a React frontend. It monitors streamers, downloads VOD audio via yt-dlp, transcribes with OpenAI Whisper (or local faster-whisper), and stores transcripts as JSON files. State is persisted in JSON files — no database.

## Commands

### Backend
```bash
# Install dependencies
uv sync

# Run the API server
uv run uvicorn src.api.main:app --reload

# Run the full pipeline (monitor → download → transcribe)
uv run python -m src.pipeline

# Manually transcribe a specific VOD
uv run python scripts/transcribe_vod.py <username> <vod_id>

# Run tests
uv run pytest
```

### Frontend (`frontend/`)
```bash
pnpm dev        # dev server
pnpm build      # tsc + vite build
pnpm lint       # eslint
```

## Architecture

### Data Flow
```
GitHub Actions cron → src/pipeline.py
  → monitor.py       (Twitch API: find new VODs from tracked streamers)
  → downloader.py    (yt-dlp: extract MP3 audio to /tmp)
  → transcriber.py   (OpenAI Whisper API) OR transcriber_local.py (faster-whisper)
  → transcripts/{username}/{vod_id}.json
```

### State Management
- `state/streamers.json` — tracked streamers (username + twitch_id)
- `state/vods.json` — VOD records with `VodStatus` enum: `PENDING → DOWNLOADING → TRANSCRIBING → COMPLETED/FAILED`
- `src/state.py` — `StateManager` handles in-memory caching + filesystem sync

### Transcript Format
```json
{
  "vod_id": "...",
  "streamer": "...",
  "title": "...",
  "text": "full transcript text",
  "transcript_metadata": {},
  "recorded_at": "ISO datetime",
  "cost": 0.0
}
```

### API (FastAPI, port 8000)
- `GET/POST /api/streamers` — list/add streamers
- `GET /api/streamers/{username}/recent` — recent VODs
- `GET /api/vods` — list all VODs (filterable by streamer/status)
- `GET /api/vods/{vod_id}/transcript` — full transcript JSON
- `GET /api/search?q=...` — substring full-text search across transcript files

### Frontend (React + Vite, port 5173)
3 routes: `/` (streamer list + VOD status), `/search` (keyword search), `/transcript/:vodId` (viewer). API base URL is hardcoded to `http://localhost:8000`.

### CI/CD
- `.github/workflows/cron.yml` — runs `src/pipeline.py` daily, auto-commits new transcripts
- `.github/workflows/test-transcription.yml` — manual dispatch to transcribe a specific VOD

## Configuration

Copy `.env.example` to `.env`:
- `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` — from dev.twitch.tv
- `OPENAI_API_KEY` — for Whisper API
- `WHISPER_USE_LOCAL=true` — switch to local faster-whisper (avoids API cost)
- `WHISPER_MODEL` — model size for local inference (`small`, `medium`, `large`)

## Key Design Decisions
- **No database**: JSON files are the source of truth. Git-friendly and stateless deployment via GitHub Actions.
- **Dual transcription**: Toggle between OpenAI API and local faster-whisper via `WHISPER_USE_LOCAL`.
- **Search is simple substring match**: `src/search.py` walks transcript JSON files — no indexing.
- **Streamers to monitor** are hardcoded in `src/pipeline.py` as `STREAMERS_TO_CHECK`.
