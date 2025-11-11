#!/usr/bin/env python3
"""Utility helpers for extracting dependency graphs from Jaeger.

This module automates the steady-state data collection phase that used to
require a manually prepared ``deps.json`` file.  We now (optionally) prime the
Social Network application with the existing wrk2 mixed workload and then call
Jaeger's ``/api/dependencies`` endpoint to obtain the live dependency graph.

The workflow mirrors the shell scripts used in the ``socialnet-resilience``
repository but keeps everything self-contained inside this codebase.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict
from urllib import error, parse, request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WRK_BIN = REPO_ROOT / "wrk2" / "wrk"
DEFAULT_LUA_SCRIPT = (
    REPO_ROOT
    / "socialNetwork"
    / "wrk2"
    / "scripts"
    / "social-network"
    / "mixed-workload.lua"
)
DEFAULT_TARGET_URL = "http://localhost:8080/index.html"
DEFAULT_JAEGER_BASE = "http://localhost:16686"
DEFAULT_LOOKBACK_MS = 60 * 60 * 1000  # 1 hour
DEFAULT_DURATION = 30
DEFAULT_RATE = 300
DEFAULT_THREADS = 2
DEFAULT_CONNECTIONS = 32
DEFAULT_OUTPUT = REPO_ROOT / "ms_collecter" / "deps.json"


class DependencyCollectionError(RuntimeError):
    """Raised when the dependency extraction step fails."""


def run_wrk(
    *,
    wrk_bin: Path,
    lua_script: Path,
    url: str,
    threads: int,
    connections: int,
    rate: int,
    duration: int,
) -> None:
    """Execute wrk2 with the mixed workload script."""

    cmd = [
        str(wrk_bin),
        f"-t{threads}",
        f"-c{connections}",
        f"-d{duration}s",
        f"-R{rate}",
        "-s",
        str(lua_script),
        url,
    ]

    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise DependencyCollectionError(
            f"wrk binary not found at '{wrk_bin}'. Build wrk2 or set --wrk-bin"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise DependencyCollectionError(
            "wrk execution failed. See the output above for details."
        ) from exc


def fetch_dependencies(
    *,
    jaeger_base: str,
    lookback_ms: int,
    timeout: int,
) -> Dict[str, Any]:
    """Retrieve the dependency graph from Jaeger."""

    end_ts = int(time.time() * 1000)
    query = parse.urlencode({"endTs": end_ts, "lookback": lookback_ms})
    url = f"{jaeger_base.rstrip('/')}/api/dependencies?{query}"

    try:
        with request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                raise DependencyCollectionError(
                    f"Jaeger returned HTTP {resp.status} while fetching dependencies"
                )
            charset = resp.headers.get_content_charset() or "utf-8"
            payload = resp.read().decode(charset)
    except error.URLError as exc:
        raise DependencyCollectionError(
            f"Failed to reach Jaeger at '{url}': {exc.reason}"
        ) from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DependencyCollectionError(
            "Received an invalid JSON document from Jaeger"
        ) from exc


def save_dependencies(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Social Network steady-state workload and extract the "
            "Jaeger dependency graph."
        )
    )
    parser.add_argument(
        "--jaeger-base-url",
        default=DEFAULT_JAEGER_BASE,
        help="Base URL for the Jaeger query service (default: %(default)s)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=DEFAULT_LOOKBACK_MS,
        help="Lookback window for dependency extraction in milliseconds (default: %(default)s)",
    )
    parser.add_argument(
        "--wrk-bin",
        type=Path,
        default=DEFAULT_WRK_BIN,
        help="Path to the wrk2 binary (default: %(default)s)",
    )
    parser.add_argument(
        "--lua-script",
        type=Path,
        default=DEFAULT_LUA_SCRIPT,
        help="Path to the wrk2 Lua workload (default: %(default)s)",
    )
    parser.add_argument(
        "--target-url",
        default=DEFAULT_TARGET_URL,
        help="Target URL exposed by nginx-thrift (default: %(default)s)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help="Number of wrk2 threads (default: %(default)s)",
    )
    parser.add_argument(
        "--connections",
        type=int,
        default=DEFAULT_CONNECTIONS,
        help="Number of wrk2 connections (default: %(default)s)",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=DEFAULT_RATE,
        help="Constant request rate for wrk2 (default: %(default)s)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION,
        help="wrk2 duration in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=15.0,
        help="Seconds to wait after the workload before querying Jaeger",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout when talking to Jaeger (default: %(default)s seconds)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Where to store the captured dependency graph (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-workload",
        action="store_true",
        help="Skip the wrk2 workload step and only query Jaeger",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.lua_script.is_file():
        raise DependencyCollectionError(
            f"wrk2 workload script not found at '{args.lua_script}'."
        )

    if not args.skip_workload:
        print(
            "[dependency_collect] Running wrk2 workload using",
            args.lua_script,
        )
        run_wrk(
            wrk_bin=args.wrk_bin,
            lua_script=args.lua_script,
            url=args.target_url,
            threads=args.threads,
            connections=args.connections,
            rate=args.rate,
            duration=args.duration,
        )
        if args.cooldown > 0:
            print(
                f"[dependency_collect] Waiting {args.cooldown:.1f}s for traces to be ingested..."
            )
            time.sleep(args.cooldown)

    print(
        "[dependency_collect] Fetching dependencies from",
        args.jaeger_base_url,
    )
    deps = fetch_dependencies(
        jaeger_base=args.jaeger_base_url,
        lookback_ms=args.lookback,
        timeout=args.timeout,
    )
    save_dependencies(deps, args.output)
    print(f"[dependency_collect] Saved dependency graph to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DependencyCollectionError as exc:
        print(f"dependency_collect: {exc}", file=sys.stderr)
        raise SystemExit(1)
