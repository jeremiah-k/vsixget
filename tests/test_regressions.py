"""Regression coverage for release review findings and request handling."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import requests

from vsixget import cli, download, marketplace
from vsixget.download import DownloadResult, download_vsix
from vsixget.errors import DownloadError, UsageError, VerificationError
from vsixget.marketplace import Build, ExtensionRef, query_versions, select_build

URL = "https://marketplace.visualstudio.com/example.vspackage"
REF = ExtensionRef("publisher", "extension")


@pytest.mark.parametrize("target", [None, "linux-x64"])
def test_latest_compatible_build(target: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    builds = [Build("3.0.0", "win32-x64"), Build("2.0.0", "linux-x64"), Build("1.0.0")]
    assert select_build(builds, target_platform=target) == Build("2.0.0", "linux-x64")


def test_platform_tie_and_older_universal_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    builds = [Build("2.0.0"), Build("2.0.0", "linux-x64"), Build("3.0.0", "win32-x64")]
    assert select_build(builds) == Build("2.0.0", "linux-x64")
    assert select_build(builds, target_platform="darwin-x64") == Build("2.0.0")
    assert select_build(builds, universal=True) == Build("2.0.0")


def response(status: int = 200, body: bytes = b"") -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = body
    result._content_consumed = True
    return result


def vsix_bytes() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("extension.vsixmanifest", "<PackageManifest/>")
    return stream.getvalue()


@pytest.mark.parametrize("version, expected_flags", [(None, 512), ("1.0.0", 1)])
def test_cli_queries_history_only_for_pin(
    version: str | None,
    expected_flags: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = requests.Session()
    session.post = Mock(
        return_value=response(
            body=json.dumps(
                {
                    "results": [
                        {
                            "extensions": [
                                {
                                    "versions": [
                                        {"version": "2.0.0", "targetPlatform": "linux-x64"},
                                        {"version": "1.0.0", "targetPlatform": "linux-x64"},
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ).encode()
        )
    )
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    monkeypatch.setattr(cli.requests, "Session", lambda: session)
    fetch = Mock(return_value=DownloadResult(tmp_path / "out.vsix"))
    monkeypatch.setattr(cli, "download_vsix", fetch)
    args = [REF.id] if version is None else [REF.id, "-v", version]
    assert cli.main(args) == 0
    assert session.post.call_args.kwargs["json"]["flags"] == expected_flags
    selected = version or "2.0.0"
    assert fetch.call_args.args[1].endswith(f"/{selected}/vspackage?targetPlatform=linux-x64")


def test_404_exit_code_and_no_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session = requests.Session()
    session.get = Mock(return_value=response(404))
    monkeypatch.setattr(cli.requests, "Session", lambda: session)
    assert cli.main([REF.id, "-v", "1.0.0", "--universal", "-d", str(tmp_path)]) == 3
    session.get.assert_called_once()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("force", [False, True])
def test_concurrent_publication_preserves_no_force(
    force: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = requests.Session()
    payload = vsix_bytes()
    session.get = Mock(return_value=response(body=payload))
    target = tmp_path / "out.vsix"
    operation = "replace" if force else ("rename" if os.name == "nt" else "link")

    def inject_competitor(original: Any) -> Any:
        def competing_publish(source: Path, destination: Path) -> None:
            target.write_bytes(b"first publisher")
            original(source, destination)

        return competing_publish

    # Inject the competing file immediately before the publication syscall,
    # after any existence check. The old os.replace path must fail this test.
    monkeypatch.setattr(os, operation, inject_competitor(getattr(os, operation)))
    if not force:
        monkeypatch.setattr(os, "replace", inject_competitor(os.replace))
    result = download_vsix(
        session, URL, tmp_path, expected_name=target.name, force=force, quiet=True
    )
    assert result == DownloadResult(target, skipped=not force)
    assert target.read_bytes() == (payload if force else b"first publisher")
    assert not list(tmp_path.glob(".vsixget-*"))


def test_directory_is_not_successfully_skipped(tmp_path: Path) -> None:
    (tmp_path / "out.vsix").mkdir()
    with pytest.raises(DownloadError, match="not a regular file"):
        download_vsix(requests.Session(), URL, tmp_path, expected_name="out.vsix", quiet=True)


def test_explicit_proxy_beats_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://environment.invalid:8080")
    monkeypatch.setenv("https_proxy", "http://environment.invalid:8080")
    explicit = "http://explicit.invalid:8080"
    session = requests.Session()
    session.proxies.update({"http": explicit, "https": explicit})
    seen: list[dict[str, str]] = []

    def send(request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        seen.append(kwargs["proxies"])
        if request.method == "POST":
            return response(
                body=b'{"results":[{"extensions":[{"versions":[{"version":"1.0.0"}]}]}]}'
            )
        return response(body=vsix_bytes())

    monkeypatch.setattr(session, "send", send)
    assert query_versions(session, REF) == [Build("1.0.0")]
    download_vsix(session, URL, tmp_path, expected_name="out.vsix", quiet=True)
    assert [proxies["https"] for proxies in seen] == [explicit, explicit]


def test_permanent_request_error_is_not_retried(tmp_path: Path) -> None:
    session = requests.Session()
    session.get = Mock(side_effect=requests.exceptions.SSLError("invalid certificate"))
    with pytest.raises(DownloadError, match="invalid certificate"):
        download_vsix(session, URL, tmp_path, expected_name="out.vsix", quiet=True)
    session.get.assert_called_once()


def test_malformed_url_is_usage_error() -> None:
    with pytest.raises(UsageError, match="invalid Marketplace URL"):
        marketplace.parse_extension_id("https://[invalid?itemName=publisher.extension")


def test_unsupported_zip_compression_is_verification_error(tmp_path: Path) -> None:
    payload = bytearray(vsix_bytes())
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    payload[local + 8 : local + 10] = b"\xff\xff"
    payload[central + 10 : central + 12] = b"\xff\xff"
    path = tmp_path / "unsupported.vsix"
    path.write_bytes(payload)
    with pytest.raises(VerificationError):
        download.verify_vsix(path)
