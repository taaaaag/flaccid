# FLACCID Roadmap & Backlog

This document tracks prioritized improvements for FLACCID across reliability, UX, providers, performance, and developer experience. It complements `docs/USAGE.md` and provider notes in `docs/providers`.

Status legend: [Planned] not started • [WIP] in progress • [Done] shipped

---

## Core Architecture
- [Planned] Strict typing (`pyright --strict`) across `src/`
- [Planned] Centralized error model (auth/network/IO/parse)
- [Done] Retry utility with exponential backoff (`src/flaccid/core/retry.py`)
- [Planned] Concurrency controls (bounded semaphores, global `--concurrency`)
- [Planned] Plugin API with capability flags and entry_points discovery
- [Planned] Task queue for downloads/indexing with retry/resume

## Providers & Metadata
- [Planned] MusicBrainz/Discogs enrichment (genres, credits) with merge strategy
- [Planned] AcoustID fingerprinting as fallback identification
- [Planned] Artwork policy (best resolution/type) and lyrics provider hooks
- [Planned] Rate-limiting/token bucket per provider

## CLI & UX
- [Planned] Global `--json`/`--quiet`/`--verbose` formatter unification
- [Done] `fla lib stats --json` (JSON output)
- [Planned] TUI for library/playlist matching (Rich)
- [Planned] Shell completion helpers for bash/zsh/fish
- [Done] `fla get --json` (light summary)
- [WIP] Dry-run modes for `get`, `lib index`

## Library & Database
- [Done] Additional indexes (album/artist)
- [Done] `fla lib vacuum` to optimize DB
- [Planned] Normalized schema (artists/albums/tracks), migrations
- [Planned] FTS5 full-text search and `fla lib search`
- [Planned] Multi-root libraries with include/exclude globs

## Downloads
- [Done] Resumable downloads via `.part` files and Range requests
- [Planned] Chunk-level retries with checksum/size validation
- [Planned] Quarantine folder for failures and requeue command
- [Planned] Post-download hooks per track/album

## Config & Secrets
- [Done] Provider docs (QOBUZ, TIDAL)
- [Planned] Profiles (`--profile NAME`) and import/export with redaction
- [Planned] `.env` support docs and precedence clarifications
- [Planned] Keyring override (`--no-keyring`), explicit backend selection

## Performance
- [Planned] Shared async HTTP connector, DNS cache, per-host limits
- [Planned] Scanner optimizations (os.scandir recursion, ignore rules)
- [Planned] Incremental hashing with cached size/mtime

## Observability & Security
- [Planned] Structured logs (JSON) with context
- [Planned] Optional Prometheus/OpenTelemetry metrics
- [Planned] SBOM generation in CI and dependency pinning w/ hashes
- [Planned] Secrets redaction in logs/tracebacks

## Testing & CI
- [Done] CI matrix: 3.10–3.13 on Ubuntu/macOS
- [Planned] Windows CI runner
- [Planned] Network mocks/contract tests for providers
- [Planned] E2E smoke tests gated by marker

## Packaging & Distribution
- [Planned] Docker image (non-root), Nix flake, Homebrew formula/Win installer
- [Planned] Optional extras: `pip install flaccid[qobuz,tidal,lyrics,dev]`

---

## Near-Term Plan (proposed)
1) Ship dry-run for `get` and `lib index` (safe, additive)
2) Add shell completion docs and helper command
3) Add concurrency flag and bounded semaphore for provider downloads
4) Start FTS5 search with a minimal `fla lib search` (read-only)

