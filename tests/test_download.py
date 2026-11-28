"""Tests for streaming downloads, filenames, and VSIX verification."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import requests
import responses

from vsixget import download
from vsixget.download import (
    DownloadResult,
    download_vsix,
    filename_from_content_disposition,
    sanitize_filename,
    verify_vsix,
)
from vsixget.errors import DownloadError, NotFoundError, VerificationError

URL = "https://marketplace.visualstudio.com/example.vspackage"


def valid_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("extension.vsixmanifest", "<PackageManifest/>")
    return buffer.getvalue()


def test_filename_from_content_disposition() -> None:
    value = 'inline; filename="ms-vscode.cpptools-1.35.6@linux-x64.vsix"'
    assert filename_from_content_disposition(value) == ("ms-vscode.cpptools-1.35.6@linux-x64.vsix")


def test_filename_from_rfc5987_content_disposition() -> None:
    value = "inline; filename*=utf-8''ms-vscode.cpptools-1.35.6%40linux-x64.vsix"
    assert filename_from_content_disposition(value) == ("ms-vscode.cpptools-1.35.6@linux-x64.vsix")


@pytest.mark.parametrize(
    ("name", "field", "expected"),
    [
        ("../../evil.vsix", "fallback.vsix", "evil.vsix"),
        (r"..\..\evil.vsix", "fallback.vsix", "evil.vsix"),
        ("bad:name?.vsix", "fallback.vsix", "bad_name_.vsix"),
        ("not-a-vsix.zip", "fallback.vsix", "fallback.vsix"),
        (None, "fallback.vsix", "fallback.vsix"),
    ],
)
def test_sanitize_filename(name: str | None, field: str, expected: str) -> None:
    assert sanitize_filename(name, field) == expected


def test_verify_vsix_accepts_manifest(tmp_path: Path) -> None:
    path = tmp_path / "valid.vsix"
    path.write_bytes(valid_zip_bytes())
    verify_vsix(path)


def test_verify_vsix_requires_manifest(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("extension/package.json", "{}")
    path = tmp_path / "no-manifest.vsix"
    path.write_bytes(buffer.getvalue())
    with pytest.raises(VerificationError, match="extension.vsixmanifest"):
        verify_vsix(path)


def test_verify_vsix_rejects_non_zip(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.vsix"
    path.write_bytes(b"not a zip")
    with pytest.raises(VerificationError):
        verify_vsix(path)


@responses.activate
def test_download_uses_content_disposition_name(tmp_path: Path) -> None:
    payload = valid_zip_bytes()
    responses.add(
        responses.GET,
        URL,
        body=payload,
        headers={
            "Content-Disposition": 'inline; filename="fixture-1.0.0@linux-x64.vsix"',
            "Content-Length": str(len(payload)),
        },
    )

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        quiet=True,
    )

    assert result == DownloadResult(tmp_path / "fixture-1.0.0@linux-x64.vsix")
    assert result.path.read_bytes() == payload
    assert not list(tmp_path.glob(".vsixget-*"))


@responses.activate
def test_existing_file_is_skipped_without_request(tmp_path: Path) -> None:
    existing = tmp_path / "fallback.vsix"
    existing.write_bytes(b"old")
    responses.add(responses.GET, URL, body=valid_zip_bytes())

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        quiet=True,
    )

    assert result.skipped is True
    assert result.path == existing
    assert existing.read_bytes() == b"old"
    assert len(responses.calls) == 0


@responses.activate
def test_missing_extension_is_not_retried(tmp_path: Path) -> None:
    responses.add(responses.GET, URL, status=404)

    with pytest.raises(NotFoundError, match="404"):
        download_vsix(
            requests.Session(),
            URL,
            tmp_path,
            expected_name="fallback.vsix",
            quiet=True,
        )

    assert len(responses.calls) == 1


@responses.activate
def test_transient_error_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = valid_zip_bytes()
    responses.add(responses.GET, URL, status=500)
    responses.add(
        responses.GET,
        URL,
        body=payload,
        headers={
            "Content-Disposition": 'filename="fixture.vsix"',
            "Content-Length": str(len(payload)),
        },
    )
    monkeypatch.setattr(download.time, "sleep", lambda _: None)

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        quiet=True,
    )

    assert result.path.exists()
    assert len(responses.calls) == 2


@responses.activate
def test_three_failures_raise_download_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses.add(responses.GET, URL, status=503)
    responses.add(responses.GET, URL, status=503)
    responses.add(responses.GET, URL, status=503)
    monkeypatch.setattr(download.time, "sleep", lambda _: None)

    with pytest.raises(DownloadError, match="after 3 attempts"):
        download_vsix(
            requests.Session(),
            URL,
            tmp_path,
            expected_name="fallback.vsix",
            quiet=True,
        )

    assert len(responses.calls) == 3


@responses.activate
def test_corrupt_body_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = valid_zip_bytes()
    responses.add(
        responses.GET,
        URL,
        body=b"not a zip",
        headers={"Content-Disposition": 'filename="fixture.vsix"'},
    )
    responses.add(
        responses.GET,
        URL,
        body=payload,
        headers={
            "Content-Disposition": 'filename="fixture.vsix"',
            "Content-Length": str(len(payload)),
        },
    )
    monkeypatch.setattr(download.time, "sleep", lambda _: None)

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        quiet=True,
    )

    assert result.path.read_bytes() == payload
    assert len(responses.calls) == 2


@responses.activate
def test_force_overwrites_existing_file(tmp_path: Path) -> None:
    existing = tmp_path / "fallback.vsix"
    existing.write_bytes(b"old")
    payload = valid_zip_bytes()
    responses.add(
        responses.GET,
        URL,
        body=payload,
        headers={
            "Content-Disposition": 'filename="fallback.vsix"',
            "Content-Length": str(len(payload)),
        },
    )

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        force=True,
        quiet=True,
    )

    assert result.skipped is False
    assert existing.read_bytes() == payload


@responses.activate
def test_nested_directory_is_created(tmp_path: Path) -> None:
    payload = valid_zip_bytes()
    responses.add(
        responses.GET,
        URL,
        body=payload,
        headers={
            "Content-Disposition": 'filename="nested.vsix"',
            "Content-Length": str(len(payload)),
        },
    )

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path / "a" / "b",
        expected_name="nested.vsix",
        quiet=True,
    )

    assert result.path.parent.is_dir()
    assert result.path.exists()


def test_format_size() -> None:
    assert download.format_size(0) == "0 B"
    assert download.format_size(1024) == "1.00 KB"
    assert download.format_size(1024**2) == "1.00 MB"


def test_filename_from_content_disposition_absent() -> None:
    assert filename_from_content_disposition(None) is None
    assert filename_from_content_disposition("") is None


@responses.activate
def test_download_progress_is_visible(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = valid_zip_bytes()
    responses.add(
        responses.GET,
        URL,
        body=payload,
        headers={
            "Content-Disposition": 'filename="progress.vsix"',
            "Content-Length": str(len(payload)),
        },
    )

    download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        quiet=False,
    )

    stderr = capsys.readouterr().err
    assert "Downloading" in stderr
    assert "Downloaded" in stderr


@responses.activate
def test_invalid_content_length_does_not_fail(tmp_path: Path) -> None:
    payload = valid_zip_bytes()
    responses.add(
        responses.GET,
        URL,
        body=payload,
        headers={
            "Content-Disposition": 'filename="invalid-length.vsix"',
            "Content-Length": "not-a-number",
        },
    )

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        quiet=True,
    )
    assert result.path.exists()


@responses.activate
def test_retry_after_header_is_honored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = valid_zip_bytes()
    responses.add(responses.GET, URL, status=429, headers={"Retry-After": "0"})
    responses.add(
        responses.GET,
        URL,
        body=payload,
        headers={
            "Content-Disposition": 'filename="retried.vsix"',
            "Content-Length": str(len(payload)),
        },
    )
    delays: list[float] = []
    monkeypatch.setattr(download.time, "sleep", lambda delay: delays.append(delay))

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        quiet=True,
    )

    assert result.path.exists()
    assert delays == [0.0]
    assert len(responses.calls) == 2


@responses.activate
def test_content_disposition_existing_file_is_skipped(tmp_path: Path) -> None:
    existing = tmp_path / "header.vsix"
    existing.write_bytes(b"old")
    responses.add(
        responses.GET,
        URL,
        body=valid_zip_bytes(),
        headers={"Content-Disposition": 'filename="header.vsix"'},
    )

    result = download_vsix(
        requests.Session(),
        URL,
        tmp_path,
        expected_name="fallback.vsix",
        quiet=True,
    )

    assert result.skipped is True
    assert existing.read_bytes() == b"old"
    assert len(responses.calls) == 1


def test_directory_creation_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    with pytest.raises(DownloadError, match="could not create download directory"):
        download_vsix(
            requests.Session(),
            URL,
            tmp_path / "nested",
            expected_name="fallback.vsix",
            quiet=True,
        )
