# Day 13 Observability Lab Template

Template repo for a 4-hour hands-on lab on Monitoring, Logging, and Observability.

## What students will build

A small FastAPI "agent" instrumented with:
- structured JSON logging
- correlation ID propagation
- PII scrubbing
- Langfuse tracing
- minimal metrics aggregation
- SLOs, alerts, and a blueprint report

This template is intentionally incomplete. Teams are expected to finish TODOs during the lab.

## Suggested lab flow (Gapped Template)

1. **Run the starter app**: Observe that logs are basic and correlation IDs are missing.
2. **Implement Correlation IDs**: Fix `app/middleware.py` so every request has a unique `x-request-id`.
3. **Enrich Logs**: Update `app/main.py` to bind user, session, and feature context to every log.
4. **Sanitize Data**: Implement the PII scrubber in `app/logging_config.py`.
5. **Verify with Script**: Run `python scripts/validate_logs.py` to check your progress.
6. **Tracing**: Send 10-20 requests and verify traces in Langfuse (ensure `observe` decorator is used).
7. **Dashboards**: Build your 6-panel dashboard from exported metrics.
8. **Alerting**: Configure alert rules in `config/alert_rules.yaml` and test them.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Tooling

```bash
# Generate requests (use --concurrency 5 to test parallel bottlenecks)
python scripts/load_test.py --concurrency 5

# Inject failures live
python scripts/inject_incident.py --scenario rag_slow

# Check your implementation progress
python scripts/validate_logs.py

# Evaluate alert_rules.yaml against the live /metrics snapshot
python scripts/check_alerts.py
```

## Restarting from scratch (after the server was stopped)

If you've closed the terminal / shut down the machine and need to bring everything back up:

```bash
# 1. Activate the existing virtualenv (created once via `python -m venv .venv`)
source .venv/bin/activate          # Git Bash / macOS / Linux
# .venv\Scripts\activate            # Windows PowerShell / cmd

# 2. (Optional) wipe generated logs for a clean validate_logs.py run
rm data/logs.jsonl data/audit.jsonl
# in-memory /metrics + /metrics/timeseries counters reset automatically on restart

# 3. Start the API server (keep this terminal open)
uvicorn app.main:app --reload

# 4. In a second terminal, generate traffic
python scripts/load_test.py
python scripts/load_test.py --concurrency 5

# 5. Open the dashboard
#    http://127.0.0.1:8000/dashboard
#    (auto-refreshes every 20s; use "Refresh now" / "Pause auto-refresh" as needed)

# 6. Re-validate and check alerts
python scripts/validate_logs.py
python scripts/check_alerts.py
```

Step 2 is only needed if you want metrics/`validate_logs.py` to start from zero again; the
app works fine without it (it just appends to the existing `data/logs.jsonl`/`data/audit.jsonl`).
The "How to run / restart this lab from scratch" panel at the bottom of `/dashboard` repeats
this quick guide for convenience.

## Repo map

```text
app/
  main.py                FastAPI app
  agent.py               core agent pipeline
  logging_config.py      structlog config
  middleware.py          correlation ID middleware
  pii.py                 scrubbing helpers
  tracing.py             Langfuse helpers
  schemas.py             request/response/log models
  metrics.py             in-memory metrics helpers
  incidents.py           toggles for injected failures
  mock_llm.py            deterministic fake LLM
  mock_rag.py            deterministic fake retrieval
config/
  slo.yaml               starter SLOs
  alert_rules.yaml       starter alerts
  logging_schema.json    expected log schema
scripts/
  load_test.py           generate requests
  inject_incident.py     flip incident toggles
  validate_logs.py       schema checks for logs
data/
  sample_queries.jsonl   requests for testing
  expected_answers.jsonl starter quality checks
  incidents.json         scenario descriptions
  logs.jsonl             app output target
  audit.jsonl            optional audit log output

docs/
  blueprint-template.md  team submission template
  alerts.md              runbook + alert worksheet
  dashboard-spec.md      6-panel dashboard checklist
  grading-evidence.md    evidence collection sheet
  mock-debug-qa.md       oral/written debugging questions
```

## Team role suggestion

- Member A: logging + PII
- Member B: tracing + tags
- Member C: SLO + alerts
- Member D: load test + incident injection
- Member E: dashboard + evidence
- Member F: blueprint + demo lead

## Grading policy (60/40 Split)

Your final grade is calculated as follows:

1. **Group Score (60%)**: 
   - **Technical Implementation (30 pts)**: Verified by `validate_logs.py` and live system state.
   - **Incident Response (10 pts)**: Accuracy of your root cause analysis in the report.
   - **Live Demo (20 pts)**: Team presentation and system demonstration.
2. **Individual Score (40%)**:
   - **Individual Report (20 pts)**: Quality of your specific contributions in `docs/blueprint-template.md`.
   - **Git Evidence (20 pts)**: Traceable work via commits and code ownership.

**Passing Criteria**: 
- All `TODO` blocks must be completed.
- Minimum of 10 traces must be visible in Langfuse.
- Dashboard must show all 6 required panels.
