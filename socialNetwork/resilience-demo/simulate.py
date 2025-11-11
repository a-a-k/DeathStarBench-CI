#!/usr/bin/env python3
"""Offline resilience simulator for the Social Network demo.

The CLI follows the SIM_CLI_CONTRACT:
    --graph <deps.json> --replicas <yaml> --pfail <float> --out <json>

The simulator consumes a Jaeger-style dependencies graph and replica counts to
produce endpoint level reliability estimates. The implementation intentionally
keeps the model lightweight so it can execute quickly inside CI while still
showing how replicas affect the estimated availability of each critical
endpoint.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional

ARTIFACT_ROOT = Path(__file__).resolve().parent


def _load_simple_yaml(path: Path) -> Dict[str, int]:
    """Load a simple key: value mapping from a tiny YAML subset.

    The artifacts that accompany the demo only require flat mappings, so we
    avoid bringing an additional YAML dependency into the environment.
    """

    data: Dict[str, int] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"Invalid line in {path}: {raw_line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            raise ValueError(f"Missing value for {key!r} in {path}")
        try:
            data[key] = int(value)
        except ValueError as exc:  # pragma: no cover - defensive path
            raise ValueError(f"Non-integer replica count for {key!r}") from exc
    return data


def _fetch_graph_from_jaeger(target: Path, url: str) -> None:
    """Refresh the dependency graph from a Jaeger dependencies API."""

    query = urllib.parse.urljoin(url.rstrip("/") + "/", "api/dependencies")
    # The demo does not expose time range knobs; 6 hours is a sensible default
    # that returns a stable snapshot in most deployments.
    params = urllib.parse.urlencode({"lookback": 6 * 60 * 60})
    req = urllib.request.Request(f"{query}?{params}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(
            f"[simulate] Warning: failed to refresh dependencies from {query}: {exc}",
            file=sys.stderr,
        )
        return

    try:
        json.loads(payload)
    except json.JSONDecodeError:
        print(
            "[simulate] Warning: Jaeger response was not valid JSON; keeping the saved graph.",
            file=sys.stderr,
        )
        return

    target.write_text(payload + "\n")
    print(f"[simulate] Dependencies graph refreshed from {query}")


def _load_graph(path: Path) -> Mapping[str, object]:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        dependencies = data
        entrypoints: Mapping[str, List[str]] = {}
        metadata: MutableMapping[str, object] = {}
    elif isinstance(data, dict):
        dependencies = data.get("dependencies", [])
        entrypoints = data.get("entrypoints", {})
        metadata = {k: v for k, v in data.items() if k not in {"dependencies", "entrypoints"}}
    else:  # pragma: no cover - defensive guard
        raise ValueError("Unsupported graph format")
    return {
        "dependencies": dependencies,
        "entrypoints": entrypoints,
        "metadata": metadata,
    }


def _derive_entrypoints(dependencies: Iterable[Mapping[str, str]]) -> Dict[str, List[str]]:
    """Fallback entrypoints when the graph does not provide them explicitly."""
    # The fallback chooses every unique parent as a pseudo-endpoint so the demo
    # continues to operate even if a minimal Jaeger dump is provided.
    entrypoints: Dict[str, List[str]] = {}
    for dep in dependencies:
        parent = dep.get("parent")
        child = dep.get("child")
        if not parent or not child:
            continue
        endpoint_key = f"/{parent}"
        entrypoints.setdefault(endpoint_key, [])
        if parent not in entrypoints[endpoint_key]:
            entrypoints[endpoint_key].append(parent)
        if child not in entrypoints[endpoint_key]:
            entrypoints[endpoint_key].append(child)
    return entrypoints


def _service_reliability(pfail: float, replicas: int) -> float:
    replicas = max(1, replicas)
    pf = max(0.0, min(1.0, pfail))
    # Independent replicas lower the joint failure probability geometrically.
    joint_failure = pf ** replicas
    return max(0.0, min(1.0, 1.0 - joint_failure))


def _path_reliability(path_services: Iterable[str], reliabilities: Mapping[str, float]) -> float:
    score = 1.0
    seen: set[str] = set()
    for service in path_services:
        if service in seen:
            continue
        seen.add(service)
        score *= reliabilities.get(service, 1.0)
    return max(0.0, min(1.0, score))


def run_simulation(graph_path: Path, replicas_path: Path, pfail: float, out_path: Path) -> Mapping[str, object]:
    if pfail < 0:
        raise ValueError("pfail must be >= 0")

    jaeger_url = os.environ.get("JAEGER_URL")
    if jaeger_url:
        _fetch_graph_from_jaeger(graph_path, jaeger_url)

    graph_payload = _load_graph(graph_path)
    dependencies = graph_payload["dependencies"]
    entrypoints: Dict[str, List[str]] = dict(graph_payload["entrypoints"])  # shallow copy
    if not entrypoints:
        entrypoints = _derive_entrypoints(dependencies)

    replicas = _load_simple_yaml(replicas_path)

    service_reliability: Dict[str, float] = {}
    for dep in dependencies:
        parent = dep.get("parent")
        child = dep.get("child")
        if parent:
            service_reliability.setdefault(
                parent,
                _service_reliability(pfail, replicas.get(parent, 1)),
            )
        if child:
            service_reliability.setdefault(
                child,
                _service_reliability(pfail, replicas.get(child, 1)),
            )

    # Include services that never appear in the dependency list.
    for service, count in replicas.items():
        service_reliability.setdefault(service, _service_reliability(pfail, count))

    endpoint_results: Dict[str, Dict[str, object]] = {}
    for endpoint, services in sorted(entrypoints.items()):
        reliability = _path_reliability(services, service_reliability)
        endpoint_results[endpoint] = {
            "services": services,
            "reliability": reliability,
            "service_reliability": {svc: service_reliability.get(svc, 1.0) for svc in services},
        }

    mode = "norepl" if replicas_path.stem.lower().startswith("norepl") else "repl"

    summary = {
        "pfail": pfail,
        "replicas_file": str(replicas_path),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "min_reliability": min((ep["reliability"] for ep in endpoint_results.values()), default=1.0),
        "max_reliability": max((ep["reliability"] for ep in endpoint_results.values()), default=1.0),
        "entrypoint_count": len(endpoint_results),
        "mode": mode,
    }

    payload = {
        "metadata": graph_payload.get("metadata", {}),
        "summary": summary,
        "service_reliability": service_reliability,
        "endpoints": endpoint_results,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the offline resilience simulator")
    parser.add_argument("--graph", required=True, type=Path, help="Path to the Jaeger dependencies dump")
    parser.add_argument("--replicas", required=True, type=Path, help="YAML file describing replica counts")
    parser.add_argument("--pfail", required=True, type=float, help="Failure probability prior")
    parser.add_argument("--out", required=True, type=Path, help="Write the JSON report to this file")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    run_simulation(args.graph, args.replicas, args.pfail, args.out)
    print(f"[simulate] Results written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
