# Changelog

## [Unreleased]
- General fixes and docs updates.

## [0.2.0] - 2025-08-28
- Remove `musictools` package and CLI script.
  - Dropped from `pyproject.toml` packages and scripts.
  - Deleted `src/musictools/` source tree.
  - The active CLI is `fla` (package `flaccid`).
- Migration notes:
  - Replace imports `from musictools.cli import app` with `from flaccid.cli import app`.
  - Use `fla config` and `fla lib` commands instead of `musictools` equivalents.
  - If you relied on `musictools`-specific helpers, port them to `flaccid` or vendor as needed.

## [0.1.x]
- Initial public toolkit structure with `flaccid` as primary package and a temporary `musictools` shim.
