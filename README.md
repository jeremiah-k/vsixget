# vsixget

[![PyPI](https://img.shields.io/pypi/v/vsixget)](https://pypi.org/project/vsixget/)
[![CI](https://github.com/jeremiah-k/vsixget/actions/workflows/ci.yml/badge.svg)](https://github.com/jeremiah-k/vsixget/actions/workflows/ci.yml)

A Python tool for downloading VSIX files from the Visual Studio Marketplace.

## Features

- Downloads the latest version by default, with no prompt
- Accepts `publisher.extension`, Marketplace URLs, and `vscode:extension/...` URIs
- Platform-aware downloads with automatic host detection
- Optional explicit version, target platform, or universal build
- Streaming progress, transient-failure retries, and VSIX manifest verification
- Safe file naming from the Marketplace response, with skip/force handling
- Quiet mode for scripts

## Requirements

- Python 3.11 or newer

## Installation

### From PyPI (recommended)

```bash
pipx install vsixget
```

or:

```bash
pip install vsixget
```

[pipx](https://pipx.pypa.io/stable/) is recommended for CLI tools because it keeps
the tool in an isolated environment and puts `vsixget` on your PATH.

### From source

```bash
git clone https://github.com/jeremiah-k/vsixget.git
cd vsixget
python -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
```

## Usage

```bash
# Latest version, no prompt
vsixget CodeRabbit.coderabbit-vscode

# Marketplace URL
vsixget "https://marketplace.visualstudio.com/items?itemName=ms-python.python"

# Specific extension version
vsixget -v 2023.4.1 ms-python.python

# Choose a version interactively
vsixget -i ms-python.python

# Choose a download directory
vsixget -d ~/Downloads ms-python.python

# Download a build for another platform
vsixget --target-platform win32-x64 ms-vscode.cpptools

# Force the newest universal build
vsixget --universal ms-vscode.cpptools

# Overwrite an existing file, or suppress output
vsixget --force ms-python.python
vsixget --quiet ms-python.python

# Show the installed vsixget version
vsixget --version
```

`-v/--extension-version` sets the extension version; `--version` prints the
`vsixget` version.

## Behavior

- **Latest by default.** No Enter key or `--latest` is required. `--latest` is
  still accepted for compatibility, but cannot be combined with `-v`.
- **Platform-aware.** The tool reads the Marketplace's latest build for each target
  platform and downloads the newest one matching the current host, even if another
  platform has a newer version. If no matching platform build exists, it falls back
  to the newest universal build when available. With `-v` and no platform override,
  historical builds are searched for the requested version. Use
  `--target-platform` for a specific build and `--universal` for maximum
  compatibility.
- **Safe filenames.** The filename from the Marketplace `Content-Disposition` header
  is used when present, so platform-specific packages keep their `@linux-x64`-style
  suffix.
- **Existing files are skipped.** Pass `--force` to overwrite. On POSIX, safe
  no-overwrite publication requires a filesystem that supports hard links.
- **Progress goes to stderr; the final path goes to stdout.** `--quiet` suppresses
  both.
- **Exit codes:** `0` success, `1` download or runtime failure, `2` usage error,
  `3` extension/version/platform not found, `130` cancelled.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
pytest
ruff check .
ruff format --check .
```

The test suite mocks the Marketplace and never requires network access. The
`integration` marker is reserved for optional real-Marketplace tests.

## License

MIT. See [LICENSE](LICENSE).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
