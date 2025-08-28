# Improvements and Roadmap

This document tracks near-term improvements and medium-term plans for **flaccid** (formerly referenced as musictools). All references have been standardized to "flaccid" for consistency.

Note: If "musictools" refers to a legacy or subproject name, clarify scope and migration. Do not commit secrets (API keys, tokens, passwords) to the repository; use the OS keychain via Keyring or a gitignored `.secrets.toml`.

## Test Coverage (CLI and Core)

- Extend CLI tests:
  - [ ] `playlist`: Parse `JSON`/`M3U`/`TXT` happy paths + error cases
    - Acceptance: Use `pytest` fixtures for input files; assert parsed outputs match snapshots; cover malformed inputs with raised exceptions.
  - [ ] `library`: Scan, add, and db persistence smoke tests
    - Acceptance: Mock file system with `tmp_path`; verify DB entries via queries; ensure no data loss on restarts.
  - [ ] `download`: Dry-run mode for URL resolution (mock network)
    - Acceptance: Use `requests-mock`/`aiohttp` mocks for HTTP stubbing; assert no actual downloads occur; verify resolved metadata.
  - [ ] Global flags: `--verbose` / `--debug` logging behavior
    - Acceptance: Capture logs with `caplog`; assert log levels and contents match expectations.
  - [ ] Help output: Footer points to `CONFIG.md`; plain vs rich formatting via env
    - Acceptance: Run with/without `RICH` env; snapshot outputs; verify links are clickable in rich mode.
- Core config:
  - [ ] Round-trip set/get for nested lists and dicts
    - Acceptance: Set complex structures; get and assert equality; handle serialization edge cases.
  - [ ] Validate env casting for ints/floats/paths edge cases
    - Acceptance: Test invalid casts raise `ValueError`; valid ones convert correctly (e.g., "3.14" to float).

Priority: P0 (Critical for reliability)  
Assignee: TBD  
Target Milestone: v0.2.0

## CLI UX Enhancements

- Config visibility:
  - [ ] Add "Source" column by default when output is a TTY (toggle off via flag)
    - Acceptance: Detect TTY with `sys.stdout.isatty()`; include column; add `--no-sources` flag to hide.
  - [ ] Add `--no-sources` to force-hide in table mode
    - Acceptance: Flag overrides TTY detection; verify in tests with mocked stdout.
  - [ ] Add `fla config show --json` output (new command)
    - Acceptance: Implement a `config` command group with `show --json`; output JSON-serialized config paths; validate against schema.
- Help/Docs:
  - [ ] Add one-liner at bottom of `fla --help` linking to [CONFIG.md](./CONFIG.md) and online docs (verify links)
    - Acceptance: Snapshot help output; click-test links in integration.
  - [ ] Add subcommand-specific epilog tips (`download`, `playlist`)
    - Acceptance: Each subcommand has 1–2 tips; e.g., "Use --dry-run to preview downloads."

Priority: P1 (High)  
Assignee: TBD  
Target Milestone: v0.2.0

## Playlist Matching

- Matching controls:
  - [ ] Expose ratio algorithm options (`token_set_ratio`, `partial_ratio`)
    - Acceptance: Add `--ratio-type` flag; default to `token_set_ratio`; test matching differences.
  - [ ] Per-field weights (title/artist/album)
    - Acceptance: Configurable via `config set matching.weights.title 0.5`; apply in scoring; test weighted vs unweighted.
  - [ ] Normalize common "featuring"/remaster annotations
    - Acceptance: Strip "(feat. Artist)" and "(Remastered)" in matching; preserve in outputs.
- Output:
  - [ ] Include source column in match tables
    - Acceptance: Add column like config visibility; TTY-aware.
  - [ ] Export detailed JSON with reasons and confidence intervals
    - Acceptance: JSON includes `match_reason` and `confidence: [low, high]`; validate schema.

Priority: P1 (High)  
Assignee: TBD  
Target Milestone: v0.3.0

## Qobuz Integration

- Auth & headers:
  - [ ] Detect expired `user_auth_token` and prompt re-login automatically
    - Acceptance: On 401, trigger login flow; store in secure keychain (e.g., macOS Keychain); mask in logs.
  - [ ] Cache `app_id`/`secret` resolution and handle 401/403 gracefully
    - Acceptance: Cache with TTL (e.g., 24h); never commit to repo; redact in CI/logs.
- Downloads:
  - [ ] Retry with backoff on transient network errors
    - Acceptance: Use exponential backoff (base=0.5s, max=30s, jitter); retry 429/5xx up to 5 times; log retries at DEBUG.
  - [ ] Select highest available quality automatically when user selects `LOSSLESS`
    - Acceptance: Query available formats; fallback gracefully; prefer FLAC over MP3.

Security Note: Always use secure storage for tokens (e.g., keyring library). Implement rotation policy (e.g., refresh every 7 days). Avoid logging sensitive data.

Priority: P0 (Critical)  
Assignee: TBD  
Target Milestone: v0.2.0

## Configuration Model

- Types and validation:
  - [ ] Add enum types for quality values
    - Acceptance: Enum: `LOSSLESS`, `HI_RES`, `MP3_320`; validate on set and document provider mapping.
  - [ ] Validate thresholds: auto >= review at assignment time
    - Acceptance: If `auto_threshold` < `review_threshold`, raise error; test boundaries.
  - [ ] `CONFIG.md`: Ensure it’s generated or validated against the model
    - Acceptance: Script to generate from model; diff-check in CI.

Priority: P1 (High)  
Assignee: TBD  
Target Milestone: v0.2.0

## CI / Tooling

- [ ] Add caching for Poetry and ruff/mypy/pytest
  - Acceptance: GitHub Actions cache keys based on `pyproject.toml` hash; restore on matrix (Python 3.8–3.12, Ubuntu/macOS).
- [ ] Add coverage reporting threshold and upload artifact
  - Acceptance: Use `pytest-cov`; generate `coverage.xml`; fail if <80%; upload to Codecov.
- [ ] Add macOS runner smoke test (ensure keychain paths don’t break tests)
  - Acceptance: Stub keychain with env vars; gate tests with `if sys.platform == 'darwin'`.

Priority: P2 (Medium)  
Assignee: TBD  
Target Milestone: v0.3.0

## Packaging & Distribution

- [ ] Publish to PyPI under a unique name (check availability for "flaccid-music" or similar); add install docs
  - Acceptance: Verify name on PyPI; update `pyproject.toml` with metadata (license: MIT, classifiers, project.urls); sign with sigstore; provide `pip install` instructions in README.
- [ ] Provide a standalone zipapp or single-file launcher for non-Python users
  - Acceptance: Use `shiv` or `zipapp`; test cross-platform; include in releases.

Priority: P2 (Medium)  
Assignee: TBD  
Target Milestone: v0.3.0

## Performance & Reliability

- [ ] Use a single `requests.Session` per command; set timeouts globally
  - Acceptance: Session with `timeout=(5, 30)`; shared across modules; injectable for tests.
- [ ] Add structured logging mode (JSON) for better debugging
  - Acceptance: `--log-format json`; use `structlog`; test parsing.

Central HTTP Policy: Apply retries/timeouts consistently across all integrations (not just Qobuz).

Priority: P0 (Critical)  
Assignee: TBD  
Target Milestone: v0.2.0

## Cleanup

- [x] Remove unused legacy trees (`archive/`, `third_party/`) from the repository and ignore going forward
  - Acceptance: Add to `.gitignore`; verify in CI cleanup job.
- [ ] Periodically prune `__pycache__/` and compiled debris in CI
  - Acceptance: Add `find . -name "__pycache__" -exec rm -rf {} +` in CI script.

Priority: P2 (Medium)  
Assignee: TBD  
Target Milestone: v0.1.0

## Release/Versioning Process

- [ ] Define SemVer adherence, changelog format (Keep a Changelog), and release workflow (tags, automation, release notes)
  - Acceptance: Document in CONTRIBUTING.md; automate with GitHub Actions.

Priority: P1 (High)  
Assignee: TBD  
Target Milestone: v0.2.0

If you want to propose or prioritize items, open an issue or PR against this document.

Verification Checklist:
- [ ] Confirm `CONFIG.md` exists and is up-to-date.
- [ ] Validate all links (e.g., online docs).
- [ ] Check for stale "already added" notes.
- [ ] Confirm secrets are not stored in `settings.toml` and `.secrets.toml` is gitignored.
