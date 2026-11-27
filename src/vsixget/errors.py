"""Expected failures shared by the vsixget modules."""

from __future__ import annotations


class VsixgetError(Exception):
    """Base class for expected user-facing failures."""

    exit_code: int = 1


class UsageError(VsixgetError):
    """The supplied arguments are not usable."""

    exit_code: int = 2


class NotFoundError(VsixgetError):
    """The extension, version, or platform could not be found."""

    exit_code: int = 3


class MarketplaceError(VsixgetError):
    """The Marketplace request failed."""


class DownloadError(VsixgetError):
    """The download or file write failed."""


class RetryableError(DownloadError):
    """A transient download failure that may succeed on retry."""

    retry_after: float | None

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class VerificationError(RetryableError):
    """The downloaded bytes are not a valid VSIX."""
