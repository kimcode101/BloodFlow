# SQL and mathematical tool-calling agent

This is a new executable investigation path, alongside the original precomputed
assessment reviewer. The data agent chooses SQL queries and numerical tools during
its SDK run. It does not require a precomputed forecast when started from the CLI.

## Actual callable tools

| Tool | Execution |
|---|---|
| `describe_dataset()` | Reads the six-table schema, SQL limits, source validation and totals |
| `query_snapshot_sql(request)` | Executes a SELECT with bound parameters against the isolated snapshot |
| `forecast_consumption(request)` | Computes last-day, mean, EW mean or pooled Poisson on demand |
| `backtest_models()` | Runs whole-date expanding-window mathematical comparison |
| `project_inventory(request)` | Uses a returned forecast receipt to compute FEFO shortages, expiry, coverage and buffered targets |

Example SQL request:

```json
{
  "sql": "SELECT COUNT(*) AS stock FROM units WHERE storage_site=? AND blood_type=? AND status=? AND expiry_date>?",
  "parameters": ["H1", "O-", "available", "2026-10-22"],
  "max_rows": 20
}
```

Example forecast request:

```json
{
  "site_id": "H1",
  "blood_type": "O-",
  "horizon_days": 2,
  "method": "mean",
  "trailing_window": 7,
  "smoothing_alpha": 0.4,
  "planning_policy": "floor"
}
```

The forecast tool returns a `receipt_id`. Pass that exact ID into the projection:

```json
{
  "forecast_receipt_id": "ID_RETURNED_BY_THE_FORECAST_TOOL",
  "demand_scenario": "base",
  "buffer_fraction": 0.25,
  "elapsed_exposure": 0.5
}
```

All quantities are computed by Python. The model can choose a method, horizon,
and planning scenario within bounds, but these are exploratory choices, not
approved operational policy. Poisson falls back to the mean when the history is
insufficient. Means stay fractional; targets are rounded up once. `low` and `high`
are uncalibrated planning scenarios. Dates, no-double-counting, partial-day and
expiry conventions remain those documented in `ASSESSMENT.md`.

## SQL boundary

The agent's SQL dialect is **SQLite**, scoped to an in-memory copy of one validated
snapshot. Input can come from the preserved CSVs or the PostgreSQL read-only
repeatable-read adapter. Model-authored SQL never reaches the operational database.
The six source tables are copied into the isolated query workspace; no extra
schema, credentials, audit tables or filesystem content is available to queries.

SQLite's authorizer checks actual executed operations. It allows SELECT, reads of
six named tables, and a short function allowlist. It rejects writes, DDL, ATTACH,
PRAGMA, extension loading, recursive CTEs, metadata reads and other schemas.
Read-only mode adds a second enforcement layer. Queries are limited to 8,000
characters, 50 parameters, 200 returned rows, 200,000 VM instructions or roughly
one second. Results report truncation. Tool payloads have a 96 KB output cap.
An investigation permits 32 tool attempts, 16 model turns and 180 seconds.

SQL results are exploratory evidence. A correct query is still necessary for a
meaningful interpretation; the model cannot turn a selected SQL result into an
approved requirement. All stock and historical data remain untouched.

## Audit and model output

Each successful tool call creates a content-addressed receipt containing the
snapshot, as-of time, method, parameters, values, source references and assumptions.
Receipts are persisted through the controlled audit service. Forecast projections
must reference a forecast generated within the same investigation.

The final answer includes evidence receipt IDs, numerical claims with JSON pointers,
and a review action. The backend requires source discovery, SQL, forecasting and
projection to have actually executed. Every claimed number must exactly match its
referenced tool output. A model failure or invalid claim cannot create a successful
agent-run record. Earlier tool receipts remain as audit evidence. No approval or
shipment-execution tool is exposed.

SDK tracing is disabled for this path; local audit receipts and response IDs record
the observable tool sequence. Internal private reasoning is not captured or claimed.
The final contract is structured rather than a free-text analyst narrative.

## Run without a model

```sh
.venv/bin/python -m blood_assessment.data_demo --offline --output runs/data-agent-offline
```

This performs six real tool calls: schema inspection, two SQL queries, a forecast,
a projection and backtesting. It is labeled scripted execution, not model reasoning.
The H1 O− example returns stock zero, known scheduled demand eight, and a two-day
buffered target of fourteen under the explicit demonstration assumptions.

## Run with a live model

Use a replacement API key if a key was shared in a conversation. Do not put keys
in source files, CLI arguments, audit payloads or test fixtures. Choose a model
available to the project. The program accepts an environment key or a hidden prompt:

```sh
.venv/bin/python -m blood_assessment.data_demo \
  --prompt-key --model YOUR_AVAILABLE_MODEL \
  --output runs/data-agent-live
```

The hidden prompt reads the key into process memory and does not save it. You can
instead configure `OPENAI_API_KEY` and `OPENAI_MODEL` in the local environment.
Add `--postgresql` to load the source snapshot from `DATABASE_URL`; `DATA_SCHEMA`
is restricted to `public` or `kim`. Without that flag, the source is the CSV fixture.

The output folder contains a JSON report with actual call receipts and an SQLite
audit database. Reusing the same idempotency key returns the stored result; change
`--key` (an audit request key, not a credential) for a fresh investigation.

## API

`POST /assessments/{assessment_id}/data-agent` uses the existing assessment's
snapshot and executes a fresh model-led investigation. It requires the existing
client bearer token and server-side OpenAI credentials/model:

```json
{
  "idempotency_key": "investigation-001",
  "question": "Inspect H1 O- stock, forecast the next two calendar days and project shortages requiring review."
}
```

It does not change the original assessment or approved policy.

## Verification

The tests exercise the **real Agents SDK Runner and real function-tool execution**,
with only the model responses scripted. Five model responses request schema, SQL,
forecast and projection, then return a checked numerical claim. The model receives
each executed tool result before its next response. This is stronger than replacing
the runner with a canned final answer, but it is still not a live model test.

Additional tests cover destructive SQL, schema escapes, extension loading,
recursive/resource-intensive queries, parameter injection, numeric SQL columns,
truncation, forecast recomputation, ML fallback, scenario changes, exact numerical
claims, failure persistence, idempotency, API authentication and source immutability.

```sh
.venv/bin/python -m pytest tests -q
# Opt-in; requires a locally configured key and model:
RUN_LIVE_DATA_AGENT=1 .venv/bin/python -m pytest tests/assessment/test_data_agent.py -k live_data_agent -q
```

No live OpenAI request was made during implementation because no replacement key
and model were configured in the environment. Aiven remains unconnected; all
observed source facts in this demonstration are CSV-backed.
