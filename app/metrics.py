from __future__ import annotations

import time
from collections import Counter
from statistics import mean

REQUEST_LATENCIES: list[int] = []
REQUEST_COSTS: list[float] = []
REQUEST_TOKENS_IN: list[int] = []
REQUEST_TOKENS_OUT: list[int] = []
ERRORS: Counter[str] = Counter()
TRAFFIC: int = 0
QUALITY_SCORES: list[float] = []

CACHE_HITS: int = 0
CACHE_SAVINGS_USD: float = 0.0

MAX_TIMESERIES_SAMPLES = 2000
TIMESERIES: list[dict] = []


def record_request(latency_ms: int, cost_usd: float, tokens_in: int, tokens_out: int, quality_score: float) -> None:
    global TRAFFIC
    TRAFFIC += 1
    REQUEST_LATENCIES.append(latency_ms)
    REQUEST_COSTS.append(cost_usd)
    REQUEST_TOKENS_IN.append(tokens_in)
    REQUEST_TOKENS_OUT.append(tokens_out)
    QUALITY_SCORES.append(quality_score)
    _append_sample({
        "ts": time.time(),
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "quality_score": quality_score,
        "error_type": None,
    })



def record_cache_hit(saved_cost_usd: float) -> None:
    global CACHE_HITS, CACHE_SAVINGS_USD
    CACHE_HITS += 1
    CACHE_SAVINGS_USD += saved_cost_usd


def record_error(error_type: str) -> None:
    ERRORS[error_type] += 1
    _append_sample({
        "ts": time.time(),
        "latency_ms": None,
        "cost_usd": None,
        "tokens_in": None,
        "tokens_out": None,
        "quality_score": None,
        "error_type": error_type,
    })


def _append_sample(sample: dict) -> None:
    TIMESERIES.append(sample)
    if len(TIMESERIES) > MAX_TIMESERIES_SAMPLES:
        del TIMESERIES[: len(TIMESERIES) - MAX_TIMESERIES_SAMPLES]


def timeseries(window_seconds: int = 3600) -> list[dict]:
    cutoff = time.time() - window_seconds
    return [s for s in TIMESERIES if s["ts"] >= cutoff]



def percentile(values: list[int], p: int) -> float:
    if not values:
        return 0.0
    items = sorted(values)
    idx = max(0, min(len(items) - 1, round((p / 100) * len(items) + 0.5) - 1))
    return float(items[idx])



def snapshot() -> dict:
    return {
        "traffic": TRAFFIC,
        "latency_p50": percentile(REQUEST_LATENCIES, 50),
        "latency_p95": percentile(REQUEST_LATENCIES, 95),
        "latency_p99": percentile(REQUEST_LATENCIES, 99),
        "avg_cost_usd": round(mean(REQUEST_COSTS), 4) if REQUEST_COSTS else 0.0,
        "total_cost_usd": round(sum(REQUEST_COSTS), 4),
        "tokens_in_total": sum(REQUEST_TOKENS_IN),
        "tokens_out_total": sum(REQUEST_TOKENS_OUT),
        "error_breakdown": dict(ERRORS),
        "quality_avg": round(mean(QUALITY_SCORES), 4) if QUALITY_SCORES else 0.0,
        "cache_hits": CACHE_HITS,
        "cache_savings_usd": round(CACHE_SAVINGS_USD, 6),
    }
