#!/usr/bin/env python3
"""Release gate for the Social Network resilience demo."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


class GateResult:
    def __init__(self, passed: bool, reason: str, scores: Mapping[str, List[Tuple[float, float]]]):
        self.passed = passed
        self.reason = reason
        self.scores = scores

    def as_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "scores": {
                endpoint: [
                    {"pfail": pfail, "reliability": reliability}
                    for pfail, reliability in entries
                ]
                for endpoint, entries in self.scores.items()
            },
        }


def _load_results(directory: Path) -> Dict[Tuple[float, str], Mapping[str, object]]:
    payloads: Dict[Tuple[float, str], Mapping[str, object]] = {}
    for path in sorted(directory.glob("*.json")):
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        summary = data.get("summary")
        if not isinstance(summary, dict) or "pfail" not in summary:
            continue
        pfail = float(summary.get("pfail"))
        mode = summary.get("mode")
        if not mode:
            mode = Path(summary.get("replicas_file", "")).stem or path.stem
        mode_key = mode.lower() if isinstance(mode, str) else str(mode or "").lower()
        payloads[(pfail, mode_key)] = data
    return payloads


def _select_endpoints(
    payloads: Mapping[Tuple[float, str], Mapping[str, object]],
    filters: Iterable[str],
    results_mode: Optional[str],
) -> Dict[str, List[Tuple[float, float]]]:
    selected: Dict[str, List[Tuple[float, float]]] = {}
    normalized_filters = [f for f in (flt.strip() for flt in filters) if f]
    normalized_mode = results_mode.lower() if results_mode else None

    for (pfail, mode), data in payloads.items():
        if normalized_mode and mode != normalized_mode:
            continue
        endpoints: Mapping[str, Mapping[str, object]] = data.get("endpoints", {})
        for endpoint, details in endpoints.items():
            if normalized_filters and endpoint not in normalized_filters:
                continue
            reliability = float(details.get("reliability", 1.0))
            selected.setdefault(endpoint, []).append((pfail, reliability))

    return selected


def evaluate_gate(
    results_dir: Path,
    threshold: float,
    mode: str,
    results_mode: Optional[str],
    filters: Iterable[str],
) -> GateResult:
    payloads = _load_results(results_dir)
    scores = _select_endpoints(payloads, filters, results_mode)
    if not scores:
        if results_mode:
            reason = f"No endpoints matched the filters for mode '{results_mode}'; gate skipped"
        else:
            reason = "No endpoints matched the filters; gate skipped"
        return GateResult(True, reason, scores)

    violations: Dict[str, Tuple[float, float]] = {}
    aggregate_values: List[float] = []
    for endpoint, entries in scores.items():
        entries.sort(key=lambda pair: pair[0])
        endpoint_min = min(reliability for _, reliability in entries)
        aggregate_values.append(endpoint_min)
        if endpoint_min < threshold:
            violations[endpoint] = min(entries, key=lambda pair: pair[1])

    if mode == "mean":
        aggregate = sum(aggregate_values) / len(aggregate_values)
        passed = aggregate >= threshold
        reason = f"mean reliability={aggregate:.4f} (threshold={threshold})"
    else:
        # Default behaviour is "any": fail fast if any endpoint is below the threshold.
        passed = not violations
        reason = f"min reliability={min(aggregate_values):.4f} (threshold={threshold})"

    if violations:
        formatted = ", ".join(
            f"{endpoint} @ pfail={pfail:g} -> {score:.4f}"
            for endpoint, (pfail, score) in sorted(violations.items())
        )
        reason = f"Violations: {formatted}; {reason}"

    return GateResult(passed, reason, scores)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply the resilience release gate")
    parser.add_argument("--results", required=True, type=Path, help="Directory containing simulation JSON outputs")
    parser.add_argument("--threshold", required=True, type=float, help="Reliability cutoff")
    parser.add_argument("--mode", choices=["any", "mean"], default="any", help="Gate mode")
    parser.add_argument("--results-mode", default="norepl", help="Simulation mode to evaluate (e.g. norepl or repl)")
    parser.add_argument("--filters", default="", help="Comma separated endpoint filters")
    parser.add_argument("--summary", type=Path, help="Optional file to write the evaluation summary")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    filters = [flt for flt in args.filters.split(",") if flt]
    normalized_results_mode = (args.results_mode or "").strip().lower() or None
    result = evaluate_gate(args.results, args.threshold, args.mode, normalized_results_mode, filters)

    summary_payload = {
        "threshold": args.threshold,
        "mode": args.mode,
        "results_mode": normalized_results_mode,
        "filters": filters,
        "passed": result.passed,
        "reason": result.reason,
        "endpoints": result.as_dict()["scores"],
    }
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary_payload, indent=2, sort_keys=True) + "\n")

    print(result.reason)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
