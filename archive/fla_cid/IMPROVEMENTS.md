# Improvements and Roadmap

This document tracks near-term improvements and medium-term plans for musictools.

## Test Coverage (CLI and Core)
- Extend CLI tests:
  - [ ] playlist: parse JSON/M3U/TXT happy paths + error cases
  - [ ] library: scan, add, and db persistence smoke tests
  - [ ] download: dry-run mode for URL resolution (mock network)
  - [ ] global flags: --verbose/--debug logging behavior
  - [ ] help output: footer points to CONFIG.md; plain vs rich formatting via env
- Core config:
  - [ ] Round-trip set/get for nested lists and dicts
  - [ ] Validate env casting for ints/floats/paths edge cases

## CLI UX Enhancements
- Config visibility:
  - [ ] Add Source column by default when output is a TTY (toggle off via flag)
  - [ ] Add --no-sources to force-hide in table mode
  - [ ] Add musictools config path --json output
- Help/Docs:
  - [ ] One-liner at bottom of musictools --help linking to CONFIG.md and online docs (already added; test it)
  - [ ] Add subcommand-specific epilog tips (download, playlist)

## Playlist Matching
- Matching controls:
  - [ ] Expose ratio algorithm options (token_set_ratio, partial_ratio)
  - [ ] Per-field weights (title/artist/album)
  - [ ] Normalize common feat./remaster annotations
- Output:
  - [ ] Include source column in match tables
  - [ ] Export detailed JSON with reasons and confidence intervals

## Qobuz Integration
- Auth & headers:
  - [ ] Detect expired user_auth_token and prompt re-login automatically
  - [ ] Cache app_id/secret resolution and handle 401/403 gracefully
- Downloads:
  - [ ] Retry with backoff on transient network errors
  - [ ] Select highest available quality automatically when user selects LOSSLESS

## Configuration Model
- Types and validation:
  - [ ] Add enum types for quality values
  - [ ] Validate thresholds: auto >= review at assignment time
  - [ ] CONFIG.md: ensure it’s generated or validated against the model

## CI / Tooling
- [ ] Add caching for Poetry and ruff/mypy/pytest
- [ ] Add coverage reporting threshold and upload artifact
- [ ] Add macOS runner smoke test (ensure keychain paths don’t break tests)

## Packaging & Distribution
- [ ] Publish to PyPI under a unique name; add install docs
- [ ] Provide a standalone zipapp or single-file launcher for non-Python users

## Performance & Reliability
- [ ] Use a single requests.Session per command; set timeouts globally
- [ ] Add structured logging mode (JSON) for better debugging

## Cleanup
- [x] Remove unused legacy trees (archive/, third_party/) from the repository and ignore going forward
- [ ] Periodically prune __pycache__/ and compiled debris in CI

If you want to propose or prioritize items, open an issue or PR against this document.

