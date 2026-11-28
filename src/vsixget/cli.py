"""Command-line interface for vsixget."""

from __future__ import annotations

import argparse
import math
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

import requests

from . import __version__
from .download import download_vsix
from .errors import UsageError, VsixgetError
from .marketplace import (
    Build,
    build_download_url,
    default_filename,
    parse_extension_id,
    query_versions,
    select_build,
    validate_target_platform,
    validate_version,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vsixget",
        description="Download VS Code extensions from the Visual Studio Marketplace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s CodeRabbit.coderabbit-vscode
  %(prog)s https://marketplace.visualstudio.com/items?itemName=ms-python.python
  %(prog)s -v 2023.4.1 ms-python.python
  %(prog)s -i ms-python.python
  %(prog)s --target-platform win32-x64 ms-vscode.cpptools
  %(prog)s --universal ms-vscode.cpptools
  %(prog)s -d ~/Downloads --force ms-python.python
        """,
    )

    parser.add_argument(
        "extension_id",
        help="extension identifier (publisher.extension) or Marketplace URL",
    )
    parser.add_argument(
        "-v",
        "--extension-version",
        dest="version",
        metavar="VERSION",
        help="extension version (default: latest)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="show the vsixget version and exit",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="prompt for an extension version instead of using latest",
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path("."),
        help="directory to save the VSIX file (default: current directory)",
    )
    platform_group = parser.add_mutually_exclusive_group()
    platform_group.add_argument(
        "-t",
        "--target-platform",
        metavar="TARGET",
        help="download a specific target platform (for example linux-x64 or win32-x64)",
    )
    platform_group.add_argument(
        "--universal",
        action="store_true",
        help="download the newest universal build instead of a platform build",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing VSIX file",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress progress and success output",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="network read timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--proxy",
        metavar="URL",
        help="HTTP(S) proxy URL (default: requests environment proxies)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="show a traceback for unexpected errors",
    )
    return parser


def _prompt_for_version() -> str | None:
    if not sys.stdin.isatty():
        raise UsageError("--interactive requires a terminal")
    try:
        print("Extension version (blank for latest): ", end="", file=sys.stderr, flush=True)
        entered = input().strip()
    except EOFError as exc:
        raise UsageError("interactive prompt cancelled") from exc
    return entered or None


def run(args: argparse.Namespace) -> int:
    ref = parse_extension_id(args.extension_id)

    if args.target_platform is not None:
        target_platform = validate_target_platform(args.target_platform)
    else:
        target_platform = None

    version = validate_version(args.version) if args.version is not None else None
    if args.interactive:
        entered = _prompt_for_version()
        if entered is not None:
            version = validate_version(entered)

    session = requests.Session()
    session.headers["User-Agent"] = f"vsixget/{__version__}"
    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})

    timeout = (min(10.0, args.timeout), args.timeout)

    if version is not None and (target_platform is not None or args.universal):
        build = Build(version=version, target_platform=None if args.universal else target_platform)
    else:
        builds = query_versions(session, ref, timeout=timeout, include_history=version is not None)
        build = select_build(
            builds,
            target_platform=target_platform,
            universal=args.universal,
            version=version,
        )

    if not args.quiet:
        platform = build.target_platform or "universal"
        print(f"{ref.id} {build.version} ({platform})", file=sys.stderr)

    url = build_download_url(ref, build)
    result = download_vsix(
        session,
        url,
        Path(args.directory).expanduser(),
        expected_name=default_filename(ref, build),
        force=args.force,
        quiet=args.quiet,
        timeout=timeout,
    )

    if result.skipped and not args.quiet:
        print(f"Already exists: {result.path}", file=sys.stderr)
    if not args.quiet:
        print(result.path)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.latest and args.version is not None:
        parser.error("--latest and -v/--extension-version cannot be used together")
    if args.interactive and args.version is not None:
        parser.error("--interactive and -v/--extension-version cannot be used together")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and greater than zero")

    try:
        return run(args)
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except VsixgetError as exc:
        print(f"vsixget: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:
        return 0
    except Exception as exc:  # pragma: no cover - defensive fallback
        if args.debug:
            traceback.print_exc()
        else:
            print(f"vsixget: unexpected error: {exc} (rerun with --debug)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
