"""Evaluate config/alert_rules.yaml against the live /metrics snapshot.

Usage:
    python scripts/check_alerts.py [--base-url http://127.0.0.1:8000]

For each alert rule, parses its `condition` (e.g. "latency_p95_ms > 3000 for 10m"),
maps the metric name onto the current /metrics snapshot, and prints whether the
rule would be FIRING right now. Exits with code 1 if any rule fires, so this can
be wired into CI / a cron job as a cheap synthetic alert check.

Notes on approximation: /metrics is a cumulative, in-process snapshot (no
time-windowed aggregation), so "for 10m" / "for 5m" windows are not evaluated -
this script checks whether the *current* value would breach the threshold,
which is the right signal for "did the last load test/incident trip this alert".
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx
import yaml

ALERT_RULES_PATH = Path("config/alert_rules.yaml")
CONDITION_RE = re.compile(r"(\w+)\s*(>=|<=|>|<)\s*([\w\.]+)\s*for\s*(\w+)")


def current_value(metric: str, snapshot: dict) -> float | None:
    if metric == "latency_p95_ms":
        return snapshot["latency_p95"]
    if metric == "error_rate_pct":
        errors = sum(snapshot["error_breakdown"].values())
        total = snapshot["traffic"] + errors
        return (errors / total * 100) if total else 0.0
    if metric == "hourly_cost_usd":
        # Approximate: assume all recorded requests happened within the last hour.
        errors = sum(snapshot["error_breakdown"].values())
        total = snapshot["traffic"] + errors
        return snapshot["avg_cost_usd"] * total
    if metric == "quality_score_avg":
        return snapshot["quality_avg"]
    return None


def threshold_value(threshold: str, rule: dict) -> float | None:
    if threshold.startswith("2x_baseline_hourly_cost_usd"):
        baseline = rule.get("baseline_hourly_cost_usd")
        return 2 * baseline if baseline is not None else None
    try:
        return float(threshold)
    except ValueError:
        return None


def evaluate(rule: dict, snapshot: dict) -> tuple[float | None, float | None, bool]:
    match = CONDITION_RE.match(rule["condition"])
    if not match:
        return None, None, False
    metric, op, threshold_str, _window = match.groups()

    current = current_value(metric, snapshot)
    threshold = threshold_value(threshold_str, rule)
    if current is None or threshold is None:
        return current, threshold, False

    firing = current > threshold if op in (">", ">=") else current < threshold
    return current, threshold, firing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    snapshot = httpx.get(f"{args.base_url}/metrics", timeout=10.0).json()
    rules = yaml.safe_load(ALERT_RULES_PATH.read_text(encoding="utf-8"))["alerts"]

    print("--- Alert Rule Evaluation (live /metrics snapshot) ---")
    any_firing = False
    for rule in rules:
        current, threshold, firing = evaluate(rule, snapshot)
        status = "FIRING" if firing else "OK"
        any_firing = any_firing or firing
        print(
            f"[{status}] {rule['name']} (severity={rule['severity']}): "
            f"condition='{rule['condition']}' current={current} threshold={threshold} "
            f"-> runbook={rule['runbook']}"
        )

    print(f"\n{'ALERTS FIRING' if any_firing else 'All clear'}")
    sys.exit(1 if any_firing else 0)


if __name__ == "__main__":
    main()
