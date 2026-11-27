# Changelog

## 0.2.0 - 2026-11-27

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
- Tests, GitHub Actions CI, Dependabot, and a release-version check.

### Fixed

- Platform-specific extensions no longer resolve to an old universal build
  (for example `ms-vscode.cpptools` now selects the current `1.35.x` build, not
  `1.7.1`).
- The download URL is no longer left to the Marketplace's non-deterministic
  default platform selection.
- Platform suffixes from `Content-Disposition` are preserved in filenames.
- gzip-compressed downloads no longer report impossible percentages or use the
  compressed length as an integrity check.
- 404 responses are not retried.
- Malformed Marketplace JSON, filesystem errors, interrupted downloads, and
  malformed filenames are reported without tracebacks.
- Partial downloads are cleaned up, temporary names no longer collide, and
  verification checks the VSIX manifest.

### Removed

- Automatic GitHub update checks and the redundant Marketplace connectivity
  check.
- The unverified SHA-256 output.
- The old Trunk configuration and `MANIFEST.in`.

## 0.1.0

Initial published release.
