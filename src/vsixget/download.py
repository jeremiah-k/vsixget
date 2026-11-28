"""Streaming VSIX download, verification, and retry handling."""

from __future__ import annotations

import os
import random
import re
import sys
import tempfile
import time
import zipfile
import zlib
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from .errors import DownloadError, NotFoundError, RetryableError, VerificationError, VsixgetError

CHUNK_SIZE = 1024 * 1024
MAX_ATTEMPTS = 3
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class DownloadResult:
    """The outcome of a download request."""

    path: Path
    skipped: bool = False


def format_size(size: float) -> str:
    """Format a byte count for terminal output."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def filename_from_content_disposition(value: str | None) -> str | None:
    """Extract a filename from a Content-Disposition header."""
    if not value:
        return None
    message = Message()
    message["content-disposition"] = value
    filename = message.get_filename()
    return filename.strip() if filename else None


def sanitize_filename(name: str | None, fallback: str) -> str:
    """Reduce a remote filename to a safe local basename."""
    candidate = (name or "").replace("\\", "/").split("/")[-1].strip()
    candidate = _INVALID_FILENAME_CHARS.sub("_", candidate).rstrip(" .")
    if not candidate or candidate in {".", ".."}:
        candidate = ""

    if not candidate.lower().endswith(".vsix"):
        candidate = (fallback or "").replace("\\", "/").split("/")[-1].strip()
        candidate = _INVALID_FILENAME_CHARS.sub("_", candidate).rstrip(" .")

    if not candidate or candidate in {".", ".."}:
        candidate = "download.vsix"
    if not candidate.lower().endswith(".vsix"):
        candidate = "download.vsix"
    return candidate


def _normal_file_mode() -> int:
    current_umask = os.umask(0)
    os.umask(current_umask)
    return 0o666 & ~current_umask


def verify_vsix(path: Path) -> None:
    """Verify the ZIP CRC and require a VSIX package manifest."""
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise VerificationError(f"ZIP member failed its CRC check: {bad_member}")
            if "extension.vsixmanifest" not in archive.namelist():
                raise VerificationError(
                    "downloaded file is a ZIP but not a VSIX (missing extension.vsixmanifest)"
                )
    except (zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        raise VerificationError("downloaded file is not a valid VSIX (bad ZIP)") from exc
    except OSError as exc:
        raise VerificationError(f"could not read the downloaded file: {exc}") from exc


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _response_error(response: requests.Response) -> VsixgetError:
    status = response.status_code
    if status == 404:
        return NotFoundError("extension, version, or platform was not found (HTTP 404)")
    if status == 429 or 500 <= status < 600:
        return RetryableError(
            f"Marketplace returned HTTP {status}",
            retry_after=_parse_retry_after(response.headers.get("retry-after")),
        )
    return DownloadError(f"download failed with HTTP {status}")


def _progress_line(downloaded: int, total: int, compressed: bool) -> str:
    if compressed or total <= 0:
        return f"\r  {format_size(downloaded)}"
    percentage = min(100.0, downloaded / total * 100)
    return f"\r  {percentage:5.1f}%  {format_size(downloaded)} / {format_size(total)}"


def _existing_file(target: Path) -> bool:
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise DownloadError(f"download target is not a regular file: {target}")
    return target.is_file()


def _download_once(
    session: requests.Session,
    url: str,
    directory: Path,
    expected_name: str,
    *,
    force: bool,
    quiet: bool,
    timeout: tuple[float, float],
) -> DownloadResult:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadError(f"could not create download directory {directory}: {exc}") from exc

    target = directory / sanitize_filename(expected_name, "download.vsix")
    if not force and _existing_file(target):
        return DownloadResult(target, skipped=True)

    try:
        response = session.get(
            url, stream=True, timeout=timeout, proxies=session.proxies.copy()
        )
    except requests.exceptions.SSLError as exc:
        raise DownloadError(f"could not start download: {exc}") from exc
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise RetryableError(f"could not start download: {exc}") from exc
    except requests.RequestException as exc:
        raise DownloadError(f"could not start download: {exc}") from exc

    with response:
        if response.status_code != 200:
            raise _response_error(response)

        remote_name = filename_from_content_disposition(response.headers.get("content-disposition"))
        if remote_name:
            target = directory / sanitize_filename(remote_name, target.name)
        if not force and _existing_file(target):
            return DownloadResult(target, skipped=True)

        try:
            total = int(response.headers.get("content-length", "0"))
        except (TypeError, ValueError):
            total = 0
        content_encoding = response.headers.get("content-encoding", "").lower()
        compressed = content_encoding not in {"", "identity"}

        if not quiet:
            if total > 0 and not compressed:
                print(f"Downloading {format_size(total)}...", file=sys.stderr)
            else:
                print("Downloading...", file=sys.stderr)

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=directory,
                prefix=".vsixget-",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                downloaded = 0
                last_report = 0.0
                for chunk in response.iter_content(CHUNK_SIZE):
                    if not chunk:
                        continue
                    temp_file.write(chunk)
                    downloaded += len(chunk)
                    if not quiet and sys.stderr.isatty() and time.monotonic() - last_report >= 0.1:
                        print(
                            _progress_line(downloaded, total, compressed),
                            end="",
                            file=sys.stderr,
                            flush=True,
                        )
                        last_report = time.monotonic()

            with suppress(OSError):
                os.chmod(temp_path, _normal_file_mode())
            verify_vsix(temp_path)

            if force:
                os.replace(temp_path, target)
                temp_path = None
            else:
                try:
                    if os.name == "nt":
                        # Windows rename fails if the destination already exists.
                        os.rename(temp_path, target)
                        temp_path = None
                    else:
                        # Link atomically without replacing an existing destination.
                        os.link(temp_path, target)
                except FileExistsError:
                    if _existing_file(target):
                        return DownloadResult(target, skipped=True)
                    raise

            if not quiet:
                if sys.stderr.isatty() and total > 0:
                    print(file=sys.stderr)
                print(f"Downloaded {format_size(downloaded)}", file=sys.stderr)

            return DownloadResult(target, skipped=False)
        except requests.RequestException as exc:
            raise RetryableError(f"download was interrupted: {exc}") from exc
        except OSError as exc:
            raise DownloadError(f"could not write {target}: {exc}") from exc
        finally:
            if temp_path is not None:
                with suppress(OSError):
                    temp_path.unlink(missing_ok=True)


def download_vsix(
    session: requests.Session,
    url: str,
    directory: Path,
    *,
    expected_name: str,
    force: bool = False,
    quiet: bool = False,
    timeout: tuple[float, float] = (10.0, 30.0),
) -> DownloadResult:
    """Download a VSIX, retrying transient failures up to three times."""
    last_error: RetryableError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _download_once(
                session,
                url,
                directory,
                expected_name,
                force=force,
                quiet=quiet,
                timeout=timeout,
            )
        except RetryableError as exc:
            last_error = exc
            if attempt >= MAX_ATTEMPTS:
                break
            delay = exc.retry_after
            if delay is None:
                delay = min(8.0, 2.0 ** (attempt - 1)) + random.uniform(0.0, 0.25)
            delay = min(delay, 30.0)
            if not quiet:
                print(
                    f"Download failed ({exc}); retrying in {delay:.1f}s...",
                    file=sys.stderr,
                )
            time.sleep(delay)

    raise DownloadError(f"download failed after {MAX_ATTEMPTS} attempts: {last_error}")
