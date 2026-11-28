# Changelog

## 0.2.0 - 2026-11-28

### Breaking changes

- Latest is now the default; `vsixget <extension>` no longer prompts. Use
  `--interactive` to be prompted for a version.
- `--version` now prints the `vsixget` version. Use `-v/--extension-version` for
  the extension version.
- The default download is platform-aware instead of universal-only. Use
  `--universal` to force the newest universal package.
- Existing files are skipped unless `--force` is passed.
- Python 3.11 or newer is required.

### Added

- Target-platform selection with automatic host detection.
- `--target-platform`, `--universal`, `--force`, `--quiet`, `--timeout`,
  `--proxy`, and `--debug` options.
- `python -m vsixget` support.
- Tests, GitHub Actions CI, Renovate, and a release-version check.
- A Trunk config whose CLI, plugin, and linter pins are annotated for Renovate,
  with Trunk checks running in CI.

### Fixed

- Platform-specific extensions no longer resolve to an old universal build
  (for example `ms-vscode.cpptools` now selects the current `1.35.x` build, not
  `1.7.1`).
- The download URL is no longer left to the Marketplace's non-deterministic
  default platform selection.
- Platform suffixes from `Content-Disposition` are preserved in filenames.
- gzip-compressed downloads no longer report impossible percentages or use the
  compressed length as an integrity check.
- 404 responses are not retried and exit with status `3`.
- Pinned versions are resolved from Marketplace history, and explicit targets
  choose the newest matching build before falling back to universal.
- `--universal` with a pinned version verifies that a universal build exists.
- Downloads without `--force` publish without overwriting a concurrently created
  file; POSIX publication uses hard links.
- Malformed Marketplace JSON, filesystem errors, interrupted downloads, malformed
  URLs, invalid target-platform metadata, and Windows device names are handled
  without tracebacks.
- Partial downloads are cleaned up, temporary names no longer collide, duplicate
  ZIP members are rejected, and verification checks every member plus the VSIX
  manifest.
- The interactive prompt writes to stderr, and downloaded files keep the private
  temporary-file mode without changing the process umask.
- PyPI publication runs use a tag-specific concurrency group, so pending releases are not cancelled.

### Removed

- Automatic GitHub update checks and the redundant Marketplace connectivity
  check.
- The unverified SHA-256 output.
- The Dependabot configuration and `MANIFEST.in`.

## 0.1.0

Initial published release.
