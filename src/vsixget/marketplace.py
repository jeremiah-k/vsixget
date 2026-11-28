"""Visual Studio Marketplace lookup and build selection."""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests
from packaging.version import InvalidVersion, Version

from .errors import MarketplaceError, NotFoundError, UsageError

GALLERY_BASE = "https://marketplace.visualstudio.com/_apis/public/gallery"
QUERY_URL = f"{GALLERY_BASE}/extensionquery"
API_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json;api-version=3.0-preview.1",
}
# IncludeLatestVersionOnly: the gallery returns one entry per target platform.
QUERY_FLAGS = 512
# IncludeVersions: request history rather than only the latest builds.
HISTORY_QUERY_FLAGS = 1
DEFAULT_TIMEOUT = (10.0, 30.0)

PUBLISHER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
EXTENSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*")
TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class ExtensionRef:
    """A Marketplace extension identifier."""

    publisher: str
    extension: str

    @property
    def id(self) -> str:
        return f"{self.publisher}.{self.extension}"


@dataclass(frozen=True)
class Build:
    """A downloadable build of an extension."""

    version: str
    target_platform: str | None = None

    @property
    def is_universal(self) -> bool:
        return self.target_platform is None


def parse_extension_id(value: str) -> ExtensionRef:
    """Parse a publisher.extension ID, Marketplace URL, or vscode: URI."""
    value = value.strip()
    if not value:
        raise UsageError("extension ID cannot be empty")

    if value.startswith("vscode:extension/"):
        value = value[len("vscode:extension/") :]
    elif value.startswith(("http://", "https://")):
        try:
            parsed = urlparse(value)
        except ValueError as exc:
            raise UsageError("invalid Marketplace URL") from exc
        item_names = parse_qs(parsed.query).get("itemName")
        if not item_names:
            raise UsageError("Marketplace URL must contain itemName=publisher.extension")
        value = item_names[0]

    if "." not in value:
        raise UsageError("use publisher.extension or a Marketplace URL")

    publisher, extension = (part.strip() for part in value.split(".", 1))
    if not publisher or not extension:
        raise UsageError("extension ID must contain both a publisher and an extension name")
    if not PUBLISHER_RE.fullmatch(publisher):
        raise UsageError(f"invalid publisher name: {publisher!r}")
    if not EXTENSION_RE.fullmatch(extension):
        raise UsageError(f"invalid extension name: {extension!r}")

    return ExtensionRef(publisher=publisher, extension=extension)


def validate_version(version: str) -> str:
    """Return a validated Marketplace version string."""
    version = version.strip()
    if not version or not VERSION_RE.fullmatch(version):
        raise UsageError(f"invalid extension version: {version!r}")
    return version


def validate_target_platform(target_platform: str) -> str:
    """Return a validated Marketplace targetPlatform value."""
    target_platform = target_platform.strip()
    if not target_platform or not TARGET_RE.fullmatch(target_platform):
        raise UsageError(f"invalid target platform: {target_platform!r}")
    return target_platform


def _is_alpine() -> bool:
    return Path("/etc/alpine-release").exists()


def detect_target_platform() -> str | None:
    """Return the Marketplace targetPlatform for the current host, if known."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        alpine = _is_alpine()
        if machine in {"x86_64", "amd64"}:
            return "alpine-x64" if alpine else "linux-x64"
        if machine in {"aarch64", "arm64"}:
            return "alpine-arm64" if alpine else "linux-arm64"
        if machine.startswith("armv7") or machine in {"armv6l", "arm"}:
            return "linux-armhf"
    elif system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "darwin-arm64"
        return "darwin-x64"
    elif system == "windows":
        if machine in {"arm64", "aarch64"}:
            return "win32-arm64"
        if machine in {"x86", "i386", "i686"}:
            return "win32-ia32"
        return "win32-x64"

    return None


def _version_key(build: Build) -> Version:
    try:
        return Version(build.version)
    except InvalidVersion:
        return Version("0")


def available_targets(builds: list[Build]) -> list[str]:
    """Return the sorted non-universal targets present in a build list."""
    return sorted({build.target_platform for build in builds if build.target_platform})


def _describe_available(builds: list[Build]) -> str:
    targets = available_targets(builds)
    if any(build.is_universal for build in builds):
        targets.append("universal")
    return ", ".join(targets) if targets else "none"


def query_versions(
    session: requests.Session,
    ref: ExtensionRef,
    *,
    timeout: tuple[float, float] | float = DEFAULT_TIMEOUT,
    include_history: bool = False,
) -> list[Build]:
    """Fetch latest builds per platform, or full history for a pinned version."""
    payload = {
        "filters": [
            {
                "criteria": [{"filterType": 7, "value": ref.id}],
                "pageNumber": 1,
                "pageSize": 1,
            }
        ],
        "flags": HISTORY_QUERY_FLAGS if include_history else QUERY_FLAGS,
    }

    try:
        response = session.post(
            QUERY_URL,
            json=payload,
            headers=API_HEADERS,
            timeout=timeout,
            proxies=session.proxies.copy(),
        )
    except requests.RequestException as exc:
        raise MarketplaceError(f"could not reach the Marketplace: {exc}") from exc

    if response.status_code == 404:
        raise NotFoundError(f"extension {ref.id} was not found")
    if response.status_code != 200:
        raise MarketplaceError(f"Marketplace returned HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError as exc:
        raise MarketplaceError("Marketplace returned invalid JSON") from exc

    try:
        versions = data["results"][0]["extensions"][0]["versions"]
    except (KeyError, IndexError, TypeError) as exc:
        raise NotFoundError(f"extension {ref.id} was not found") from exc

    if not isinstance(versions, list):
        raise NotFoundError(f"extension {ref.id} has no downloadable versions")

    builds: list[Build] = []
    seen: set[tuple[str, str | None]] = set()
    for item in versions:
        if not isinstance(item, dict):
            continue
        version = item.get("version")
        target_platform = item.get("targetPlatform") or None
        if not isinstance(version, str) or not version:
            continue
        if target_platform is not None and not isinstance(target_platform, str):
            continue
        key = (version, target_platform)
        if key in seen:
            continue
        seen.add(key)
        builds.append(Build(version=version, target_platform=target_platform))

    if not builds:
        raise NotFoundError(f"extension {ref.id} has no downloadable builds")
    return builds


def select_build(
    builds: list[Build],
    *,
    target_platform: str | None = None,
    universal: bool = False,
    version: str | None = None,
) -> Build:
    """Select the newest build that matches the requested version and platform."""
    if not builds:
        raise NotFoundError("no builds are available")

    if version is not None:
        builds = [build for build in builds if build.version == version]
        if not builds:
            raise NotFoundError(f"version {version} was not found")

    if universal:
        candidates = [build for build in builds if build.is_universal]
        if not candidates:
            raise NotFoundError("no universal build is available for this extension")
        return max(candidates, key=_version_key)

    target = target_platform if target_platform is not None else detect_target_platform()
    if target is not None:
        exact = [build for build in builds if build.target_platform == target]
        if exact:
            return max(exact, key=_version_key)

    fallback = [build for build in builds if build.is_universal]
    if fallback:
        return max(fallback, key=_version_key)

    requested = target_platform or f"detected platform {target or 'unknown'}"
    version_detail = f" for version {version}" if version is not None else ""
    raise NotFoundError(
        f"no build for {requested}{version_detail}; "
        f"use --target-platform or --universal; available: {_describe_available(builds)}"
    )


def build_download_url(ref: ExtensionRef, build: Build) -> str:
    """Build the vspackage URL for a specific build."""
    url = (
        f"{GALLERY_BASE}/publishers/{quote(ref.publisher, safe='')}"
        f"/vsextensions/{quote(ref.extension, safe='')}"
        f"/{quote(build.version, safe='')}/vspackage"
    )
    if build.target_platform is not None:
        url = f"{url}?{urlencode({'targetPlatform': build.target_platform})}"
    return url


def default_filename(ref: ExtensionRef, build: Build) -> str:
    """Return the fallback filename when Content-Disposition is absent."""
    platform_suffix = f"@{build.target_platform}" if build.target_platform else ""
    return f"{ref.publisher}.{ref.extension}-{build.version}{platform_suffix}.vsix"
