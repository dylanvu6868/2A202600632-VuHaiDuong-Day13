# Alert Rules and Runbooks

## Testing alert rules
Run `python scripts/check_alerts.py` against a running app (`--base-url` defaults to
`http://127.0.0.1:8000`). It parses each `condition` in `config/alert_rules.yaml`,
evaluates it against the live `/metrics` snapshot, and prints `OK`/`FIRING` per rule
with its runbook link. Exit code is `1` if any rule fires (suitable for CI/cron).

Verified: with baseline traffic all 4 rules report `OK`. After enabling the
`tool_fail` incident (`POST /incidents/tool_fail/enable`) and sending traffic, the
script reports `[FIRING] high_error_rate ... current=25.0 threshold=3.0` and exits 1.

## 1. High latency P95
- Severity: P2
- Trigger: `latency_p95_ms > 3000 for 10m` (matches `latency_p95_ms` SLO objective in `config/slo.yaml`)
- Impact: tail latency breaches SLO
- First checks:
  1. Open top slow traces in the last 1h
  2. Compare RAG span vs LLM span
  3. Check if incident toggle `rag_slow` is enabled
- Mitigation:
  - truncate long queries
  - fallback retrieval source
  - lower prompt size

## 2. High error rate
- Severity: P1
- Trigger: `error_rate_pct > 3 for 5m` (SLO objective is 2%; alert fires just above baseline noise)
- Impact: users receive failed responses
- First checks:
  1. Group logs by `error_type`
  2. Inspect failed traces
  3. Determine whether failures are LLM, tool, or schema related
- Mitigation:
  - rollback latest change
  - disable failing tool
  - retry with fallback model

## 3. Cost budget spike
- Severity: P2
- Trigger: `hourly_cost_usd > 2x_baseline_hourly_cost_usd for 15m`
- Impact: burn rate exceeds budget
- First checks:
  1. Split traces by feature and model
  2. Compare tokens_in/tokens_out
  3. Check if `cost_spike` incident was enabled
- Mitigation:
  - shorten prompts
  - route easy requests to cheaper model
  - apply prompt cache

## 4. Quality score drop
- Severity: P3
- Trigger: `quality_score_avg < 0.70 for 15m` (SLO objective is 0.75)
- Impact: users receive lower-quality / less relevant answers
- First checks:
  1. Compare `quality_score` distribution before/after the drop window via `/metrics`
  2. Check recent `payload.answer_preview` in logs for `[REDACTED_*]` markers (heuristic penalizes redacted answers)
  3. Check trace metadata `doc_count` - 0 retrieved docs lowers the score
- Mitigation:
  - roll back recent prompt/model changes
  - widen retrieval corpus / add fallback source
  - flag affected sessions for manual review
