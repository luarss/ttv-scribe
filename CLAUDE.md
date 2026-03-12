# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ttv-scribe** is a Twitch VOD transcription pipeline with a React frontend. It monitors streamers, downloads VOD audio via yt-dlp, transcribes with local faster-whisper, and stores transcripts as JSON files. State is persisted in JSON files — no database, no API server.

## Commands

### Backend
```bash
# Install dependencies
uv sync

# Run the full pipeline (monitor → download → transcribe)
uv run python -m src.pipeline

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
  → transcriber_local.py   (faster-whisper)
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
  "recorded_at": "ISO datetime"
}
```

### Frontend (React + Vite, port 5173)
2 routes: `/` (VOD list), `/transcript/:vodId` (transcript viewer). Uses Vite proxy to serve JSON files from backend directories.

### CI/CD
- `.github/workflows/cron.yml` — runs `src/pipeline.py` daily, auto-commits new transcripts
- `.github/workflows/test-transcription.yml` — manual dispatch to transcribe a specific VOD

## Configuration

Copy `.env.example` to `.env`:
- `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` — from dev.twitch.tv
- `WHISPER_MODEL` — model size for local inference (`small`, `medium`, `large`)

## Key Design Decisions
- **No database**: JSON files are the source of truth. Git-friendly and stateless deployment via GitHub Actions.
- **Local transcription**: Uses faster-whisper for free, local transcription.
