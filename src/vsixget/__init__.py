"""vsixget - download VSIX files from the Visual Studio Marketplace."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("vsixget")
except PackageNotFoundError:  # pragma: no cover - source tree without an install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
