"""Tests for CLI defaults, prompts, and error handling."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from vsixget import __version__, cli
from vsixget.download import DownloadResult
from vsixget.errors import NotFoundError
from vsixget.marketplace import Build


class FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.proxies: dict[str, str] = {}


def fake_session() -> FakeSession:
    return FakeSession()


def test_default_uses_latest_without_prompt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    prompts: list[str] = []

    def fail_input(prompt: str) -> str:
        prompts.append(prompt)
        raise AssertionError("default invocation must not prompt")

    monkeypatch.setattr("builtins.input", fail_input)
    monkeypatch.setattr(cli.requests, "Session", fake_session)
    monkeypatch.setattr(cli, "query_versions", lambda session, ref, *, timeout: [Build("1.0.0")])
    output = DownloadResult(tmp_path / "out.vsix")

    def fake_download(*args: Any, **kwargs: Any) -> DownloadResult:
        return output

    monkeypatch.setattr(cli, "download_vsix", fake_download)

    assert cli.main(["publisher.extension"]) == 0
    captured = capsys.readouterr()
    assert prompts == []
    assert "out.vsix" in captured.out
    assert "publisher.extension 1.0.0 (universal)" in captured.err


def test_quiet_suppresses_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli.requests, "Session", fake_session)
    monkeypatch.setattr(cli, "query_versions", lambda session, ref, *, timeout: [Build("1.0.0")])
    monkeypatch.setattr(
        cli,
        "download_vsix",
        lambda *args, **kwargs: DownloadResult(tmp_path / "out.vsix"),
    )

    assert cli.main(["publisher.extension", "--quiet"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_version_flag_prints_tool_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert f"vsixget {__version__}" in capsys.readouterr().out


def test_interactive_prompts_and_uses_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: "1.2.3")
    monkeypatch.setattr(cli.requests, "Session", fake_session)
    monkeypatch.setattr(cli, "query_versions", lambda session, ref, *, timeout: [Build("1.2.3")])
    urls: list[str] = []

    def fake_download(session: Any, url: str, *args: Any, **kwargs: Any) -> DownloadResult:
        urls.append(url)
        return DownloadResult(tmp_path / "out.vsix")

    monkeypatch.setattr(cli, "download_vsix", fake_download)

    assert cli.main(["publisher.extension", "--interactive"]) == 0
    assert urls and "1.2.3" in urls[0]
    assert "1.2.3" in capsys.readouterr().err


def test_interactive_requires_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", types.SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(cli.requests, "Session", fake_session)
    monkeypatch.setattr(cli, "query_versions", lambda session, ref, *, timeout: [Build("1.0.0")])

    assert cli.main(["publisher.extension", "--interactive"]) == 2
    assert "requires a terminal" in capsys.readouterr().err


def test_explicit_version_and_target_skips_marketplace_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli.requests, "Session", fake_session)

    def fail_query(*args: Any, **kwargs: Any) -> list[Build]:
        raise AssertionError("metadata should not be queried")

    monkeypatch.setattr(cli, "query_versions", fail_query)
    urls: list[str] = []

    def fake_download(session: Any, url: str, *args: Any, **kwargs: Any) -> DownloadResult:
        urls.append(url)
        return DownloadResult(tmp_path / "out.vsix")

    monkeypatch.setattr(cli, "download_vsix", fake_download)

    assert cli.main(["publisher.extension", "-v", "1.2.3", "--target-platform", "win32-x64"]) == 0
    assert urls and "1.2.3" in urls[0]
    assert "targetPlatform=win32-x64" in urls[0]


def test_marketplace_not_found_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.requests, "Session", fake_session)

    def fail_query(*args: Any, **kwargs: Any) -> list[Build]:
        raise NotFoundError("extension was not found")

    monkeypatch.setattr(cli, "query_versions", fail_query)

    assert cli.main(["publisher.extension"]) == 3
    assert "extension was not found" in capsys.readouterr().err


def test_latest_and_explicit_version_conflict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["publisher.extension", "--latest", "-v", "1.2.3"])
    assert exc.value.code == 2
    assert "cannot be used together" in capsys.readouterr().err


def test_platform_options_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "publisher.extension",
                "--target-platform",
                "linux-x64",
                "--universal",
            ]
        )
    assert exc.value.code == 2


def test_non_positive_timeout_is_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["publisher.extension", "--timeout", "0"])
    assert exc.value.code == 2


def test_force_is_forwarded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli.requests, "Session", fake_session)
    monkeypatch.setattr(cli, "query_versions", lambda session, ref, *, timeout: [Build("1.0.0")])
    captured: dict[str, Any] = {}

    def fake_download(*args: Any, **kwargs: Any) -> DownloadResult:
        captured.update(kwargs)
        return DownloadResult(tmp_path / "out.vsix")

    monkeypatch.setattr(cli, "download_vsix", fake_download)

    assert cli.main(["publisher.extension", "--force"]) == 0
    assert captured["force"] is True


def test_python_m_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy

    monkeypatch.setattr(cli, "main", lambda: 0)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("vsixget", run_name="__main__")
    assert exc.value.code == 0


def test_interactive_eof_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))

    def raise_eof(prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    assert cli.main(["publisher.extension", "--interactive"]) == 2
    assert "cancelled" in capsys.readouterr().err


def test_legacy_latest_flag_is_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli.requests, "Session", fake_session)
    monkeypatch.setattr(cli, "query_versions", lambda session, ref, *, timeout: [Build("1.0.0")])
    monkeypatch.setattr(
        cli,
        "download_vsix",
        lambda *args, **kwargs: DownloadResult(tmp_path / "out.vsix"),
    )

    assert cli.main(["publisher.extension", "--latest"]) == 0
