"""
vsixget - A Python tool for downloading VSIX files from the Visual Studio Marketplace.
"""

__version__ = "1.0.0"

from .downloader import main

__all__ = ["main", "__version__"]