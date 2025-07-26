"""
vsixget - A Python tool for downloading VSIX files from the Visual Studio Marketplace.
"""

__version__ = "0.1.0"

from .downloader import main

__all__ = ["main", "__version__"]
