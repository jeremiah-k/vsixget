"""Tests for Marketplace lookup and build selection."""

from __future__ import annotations

import pytest
import requests
import responses

from vsixget import marketplace
from vsixget.errors import MarketplaceError, NotFoundError, UsageError
from vsixget.marketplace import (
    QUERY_URL,
    Build,
    ExtensionRef,
    build_download_url,
    default_filename,
    detect_target_platform,
    parse_extension_id,
    query_versions,
    select_build,
    validate_target_platform,
    validate_version,
)


def cpp_builds() -> list[Build]:
    return [
        Build("1.35.6", "linux-x64"),
        Build("1.35.6", "alpine-arm64"),
        Build("1.35.6", "alpine-x64"),
        Build("1.35.6", "darwin-x64"),
        Build("1.35.6", "win32-x64"),
        Build("1.35.6", "linux-arm64"),
        Build("1.35.6", "darwin-arm64"),
        Build("1.35.6", "win32-arm64"),
        Build("1.7.1"),
    ]


def test_parse_plain_id() -> None:
    assert parse_extension_id("CodeRabbit.coderabbit-vscode") == ExtensionRef(
        "CodeRabbit", "coderabbit-vscode"
    )


def test_parse_marketplace_url() -> None:
    ref = parse_extension_id(
        "https://marketplace.visualstudio.com/items?itemName=ms-python.python&ssr=false"
    )
    assert ref == ExtensionRef("ms-python", "python")


def test_parse_vscode_uri() -> None:
    assert parse_extension_id("vscode:extension/ms-python.python") == ExtensionRef(
        "ms-python", "python"
    )


@pytest.mark.parametrize(
    "value",
    ["", "invalid", "publisher.", ".extension", "publisher/name.extension"],
)
def test_parse_invalid_id(value: str) -> None:
    with pytest.raises(UsageError):
        parse_extension_id(value)


def test_parse_url_without_item_name() -> None:
    with pytest.raises(UsageError):
        parse_extension_id("https://marketplace.visualstudio.com/items")


def test_validate_version() -> None:
    assert validate_version(" 1.2.3-beta.1 ") == "1.2.3-beta.1"
    with pytest.raises(UsageError):
        validate_version("1.2.3/../../escape")


def test_validate_target_platform() -> None:
    assert validate_target_platform("linux-x64") == "linux-x64"
    with pytest.raises(UsageError):
        validate_target_platform("../linux-x64")


def test_selects_latest_platform_build_not_old_universal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    build = select_build(cpp_builds())
    assert build == Build("1.35.6", "linux-x64")


def test_selects_explicit_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    assert select_build(cpp_builds(), target_platform="win32-x64") == Build("1.35.6", "win32-x64")


def test_universal_flag_selects_latest_universal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    assert select_build(cpp_builds(), universal=True) == Build("1.7.1")


def test_target_falls_back_to_universal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    builds = [Build("2.0.0"), Build("2.0.0", "linux-x64")]
    assert select_build(builds, target_platform="win32-x64") == Build("2.0.0")


def test_missing_target_reports_available_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    with pytest.raises(NotFoundError, match="linux-x64"):
        select_build(cpp_builds(), target_platform="freebsd-x64")


def test_universal_preferred_at_latest_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    builds = [Build("2.0.0"), Build("1.9.0", "linux-x64")]
    assert select_build(builds) == Build("2.0.0")


def test_unknown_host_without_universal_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: None)
    builds = [Build("2.0.0", "linux-x64")]
    with pytest.raises(NotFoundError, match="detected platform"):
        select_build(builds)


def test_explicit_version_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplace, "detect_target_platform", lambda: "linux-x64")
    builds = [Build("2.0.0", "linux-x64"), Build("1.0.0", "linux-x64")]
    assert select_build(builds, version="1.0.0") == Build("1.0.0", "linux-x64")


def test_missing_explicit_version_fails() -> None:
    with pytest.raises(NotFoundError, match="9.9.9"):
        select_build([Build("1.0.0")], version="9.9.9")


def test_no_universal_build_available() -> None:
    with pytest.raises(NotFoundError, match="universal"):
        select_build([Build("1.0.0", "linux-x64")], universal=True)


def test_build_download_url_without_target() -> None:
    ref = ExtensionRef("CodeRabbit", "coderabbit-vscode")
    assert build_download_url(ref, Build("0.26.2")) == (
        "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/"
        "CodeRabbit/vsextensions/coderabbit-vscode/0.26.2/vspackage"
    )


def test_build_download_url_with_target() -> None:
    ref = ExtensionRef("ms-vscode", "cpptools")
    url = build_download_url(ref, Build("1.35.6", "linux-x64"))
    assert url.endswith("/1.35.6/vspackage?targetPlatform=linux-x64")


def test_default_filename() -> None:
    ref = ExtensionRef("ms-vscode", "cpptools")
    assert default_filename(ref, Build("1.35.6", "linux-x64")) == (
        "ms-vscode.cpptools-1.35.6@linux-x64.vsix"
    )
    assert default_filename(ref, Build("1.7.1")) == "ms-vscode.cpptools-1.7.1.vsix"


@pytest.mark.parametrize(
    ("system", "machine", "alpine", "expected"),
    [
        ("Linux", "x86_64", False, "linux-x64"),
        ("Linux", "aarch64", False, "linux-arm64"),
        ("Linux", "x86_64", True, "alpine-x64"),
        ("Darwin", "arm64", False, "darwin-arm64"),
        ("Darwin", "x86_64", False, "darwin-x64"),
        ("Windows", "AMD64", False, "win32-x64"),
        ("Windows", "ARM64", False, "win32-arm64"),
        ("FreeBSD", "x86_64", False, None),
    ],
)
def test_detect_target_platform(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    alpine: bool,
    expected: str | None,
) -> None:
    monkeypatch.setattr(marketplace.platform, "system", lambda: system)
    monkeypatch.setattr(marketplace.platform, "machine", lambda: machine)
    monkeypatch.setattr(marketplace, "_is_alpine", lambda: alpine)
    assert detect_target_platform() == expected


@responses.activate
def test_query_versions_success() -> None:
    payload = {
        "results": [
            {
                "extensions": [
                    {
                        "versions": [
                            {"version": "2.0.0", "targetPlatform": "linux-x64"},
                            {"version": "2.0.0"},
                            {"version": "2.0.0", "targetPlatform": "linux-x64"},
                        ]
                    }
                ]
            }
        ]
    }
    responses.add(responses.POST, QUERY_URL, json=payload)
    builds = query_versions(requests.Session(), ExtensionRef("publisher", "extension"))
    assert builds == [
        Build("2.0.0", "linux-x64"),
        Build("2.0.0"),
    ]


@responses.activate
def test_query_versions_not_found() -> None:
    responses.add(responses.POST, QUERY_URL, json={"results": []})
    with pytest.raises(NotFoundError):
        query_versions(requests.Session(), ExtensionRef("publisher", "extension"))


@responses.activate
def test_query_versions_invalid_json() -> None:
    responses.add(responses.POST, QUERY_URL, body="{not json", status=200)
    with pytest.raises(MarketplaceError, match="invalid JSON"):
        query_versions(requests.Session(), ExtensionRef("publisher", "extension"))


@responses.activate
def test_query_versions_http_error() -> None:
    responses.add(responses.POST, QUERY_URL, status=503)
    with pytest.raises(MarketplaceError, match="503"):
        query_versions(requests.Session(), ExtensionRef("publisher", "extension"))


@responses.activate
def test_query_versions_empty_versions_list() -> None:
    responses.add(
        responses.POST,
        QUERY_URL,
        json={"results": [{"extensions": [{"versions": []}]}]},
    )
    with pytest.raises(NotFoundError, match="no downloadable builds"):
        query_versions(requests.Session(), ExtensionRef("publisher", "extension"))


@responses.activate
def test_query_versions_non_list_versions() -> None:
    responses.add(
        responses.POST,
        QUERY_URL,
        json={"results": [{"extensions": [{"versions": {"version": "1.0.0"}}]}]},
    )
    with pytest.raises(NotFoundError, match="no downloadable versions"):
        query_versions(requests.Session(), ExtensionRef("publisher", "extension"))
