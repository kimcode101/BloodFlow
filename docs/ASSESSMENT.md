# BloodFlow forecasting and assessment

**New:** [SQL and math data agent](DATA_AGENT.md) adds model-selected SQL queries and on-demand forecasting/projection tool calls. The original reviewer described below remains available.

The assessment package adds validated snapshots, forecasting, FEFO projections,
reviewable requirements, an OpenAI Agents SDK agent, append-only audit persistence,
and a FastAPI service. It never updates `units`, `transfers`, `daily_usage`, or
confirmed operational requirements. Proposals are hypothetical.

Aiven is not connected. This implementation uses the preserved `data/raw/team_bundle`
CSV files, not the transformed canonical fixture. The default proposal engine is
now the integrated [dated CP-SAT graph optimizer](GRAPH_OPTIMIZER.md), adapted from
the other project. The original home-bank planner remains as legacy code only.

## Run

Python 3.11+ is required. Tested here with Python 3.14.4.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-assessment.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python -m blood_assessment.demo --output runs/assessment-demo
```

`requirements-assessment.lock.txt` records the exact tested dependency versions.
Use that file for the same Python/platform environment; the ranged requirements
support other Python versions. The demo writes `report.json` and `audit.sqlite`
only under the selected output directory. Repeat runs reuse idempotency records.
Use a fresh directory after changing source, policy, or implementation versions.

The demo includes source records, full forecasts and model comparison, scheduled
contributions, stock projections, structured deterministic assessment, an explicit
**offline demo reviewer** approval, allocation proposals and audit lineage. It
then changes the planning policy to additive stress and recomputes from the same
snapshot. It does not simulate receipt or consumption of a proposed transfer.

### Source-verified scenario (CSV, not a connected database)

The run observed 1,538 units: 777 available and 761 used; 981 transfers;
163 usage rows; and 247 planned activity rows.

- H1 has zero available O−. Activity 5 is tomorrow's liver transplant with 8 O−.
- H2 has one A− unit and a complete-day mean of 4.3333/day: 0.2308 rate-based days.
- B1 has 22 O− units; 4 expire within 3 days and 16 within 5 days.
- B2 has 4 O− units.

These numbers are calculated from the fixture on every demo run. They are not
constants in the forecasting or allocation code. With the explicit demo policy
(two-day target, 25% buffer, two-unit reserve per bank/group, uniform remaining-day
scenario), the graph optimizer proposes 14 O− from B1 to H1 in both scenarios; the stress
scenario has seven unmet planning units across the network. The proposal is larger than the transplant demand
because the approved target covers two calendar days and a buffer. This is not a
recommendation to ship either quantity in practice.

## Numerical methods and limitations

- Only observed complete dates enter training. All partial dates are excluded,
  including October 22. No full unobserved calendar day is filled with zeros.
- `daily_usage` supplies the sole consumption labels. Used units independently
  reconcile them; their quantities are never added. Missing combinations on an
  observed date become zero only after reconciliation with the supplied used-unit
  ledger. This is conditional on that ledger being complete, and the condition is
  recorded as a warning; there is no independent external completeness proof.
- Baselines: last complete day, trailing mean, and exponential weighted mean
  (`alpha=0.4`). Series with fewer than three positive observations shrink toward
  the pooled blood-group mean with two pseudo-days. This is a documented prior.
- The pooled regularized Poisson model uses site/group one-hot identifiers and
  lag/trailing-three-prior-observation usage. Preprocessing and feature generation
  fit within each expanding date fold. `alpha=1`; all-zero panels return zero.
- Entire dates are held out. Reported MAE, aggregate WAPE (null for zero actual
  denominator), signed bias, folds, observations and horizons refer to one-day
  validation only. The six-day fixture supplies three folds. Trailing mean stays
  selected unless at least five folds support more than 10% lower MAE. The ML
  candidate requires 14 complete training days. Selection remains provisional.
- Days 1–7 are consumption forecasts; days 1–14 form the planning view. The
  estimated daily rate is held constant, including frozen lag features if ML is
  selected. No weekday pattern or seven-day validated accuracy is claimed.
- Low/high scenarios are 0.5 and 1.5 times the estimated rate. They are not confidence
  or calibrated predictive intervals. The buffer is a planning choice, not a
  cumulative demand quantile. Expected quantities remain fractional.
- Default planning uses `max(all-cause forecast, known planned quantity)` each day.
  It may omit additional unscheduled demand. Additive stress is explicitly separate.
  Missing planned type/quantity stays unresolved; it is never allocated to a group.
- Remaining today is unknown unless `exposure_elapsed` is supplied. With exposure
  `e`, remaining use is `observed_today * (1-e)/e`. The demo's `e=0.5` is a uniform
  scenario, not proof that half of use happened by noon. It is never a training label.
- Date intervals use Europe/Paris, including the DST transition. Two calendar-day
  targets are not called rolling 48-hour forecasts. The demo includes remaining
  today plus the future calendar-day projections as separate intervals.
- Expiry date is exclusive: a unit dated D is unusable on D. This is a simulation
  convention, not a clinical rule. FEFO consumes fractional expected quantities;
  actual proposed unit IDs and quantities are integral. Shortages become unmet
  demand, never negative stock. No historical transfer becomes a future arrival.
- Rate-based days of supply is distinct from the expiry-aware projection. Zero
  estimated use yields null finite coverage. Expiring soon does not imply waste;
  projected unused expiry assumes the displayed demand and no future receipts.
- Target = ceiling(sum of planning requirements over target days × (1 + buffer)).
  Components are retained. Proposed priorities are fixed versioned policy: 100 for
  near-horizon shortage, otherwise 50 for near expiry, otherwise 0. They are
  reviewable indicators, not learned clinical priority or LLM weights.
- No exact historical inventory reconstruction is claimed. Same-day movements
  are not ordered when date resolution cannot establish an order.

## Agent

Set `OPENAI_API_KEY` and `OPENAI_MODEL` to use:

```sh
.venv/bin/python -m blood_assessment.demo --output runs/live-demo --live-agent
RUN_LIVE_AGENT=1 .venv/bin/python -m pytest tests/assessment -k live_agent -q
```

The ordinary demo is deterministic and does not pretend to be a live LLM run.
One SDK agent has bounded tools for data quality, findings, hospital/group
investigation, bank stock/expiry, and model comparison. The tools return snapshot,
analysis time, method/configuration, values, evidence and assumptions. There are no
SQL, shell, write, approval or shipment tools. Evidence-rich numerical assessments
are calculated by the service before the agent investigates them.

The structured agent response can only cite finding IDs, select the next review
step, and return typed numerical claims. Every claim must exactly match a stored
tool value. Free-form numerical narration is intentionally excluded. The returned
review is persisted for exact replay; provider or malformed-output failures leave
the last assessment unchanged. Ordinary CI mocks the SDK runner. Trace export is
opt-in with `BLOODFLOW_TRACE=1`; sensitive trace content stays disabled.

Implementation checked against official [agent definitions](https://developers.openai.com/api/docs/guides/agents/define-agents),
[Python quickstart](https://developers.openai.com/api/docs/guides/agents/quickstart?lang=python),
and [tracing guidance](https://developers.openai.com/api/docs/guides/agents/integrations-observability),
and exercised against installed `openai-agents==0.24.0`.

## Persistence, approval, and API

SQLAlchemy creates only `blood_assessment_records_v1` in the configured **audit**
store. Records cover snapshots, forecast outputs/configuration, assessments with
source evidence and proposed requirements/priorities, approval decisions, agent
reviews, and optimizer runs with transfer proposals. Snapshot tables and hashes
are retained, schema-isolated, as well as dependency versions, cutoff, feature
configuration and seed. References flow snapshot → forecast → assessment →
approval → optimizer run. Idempotency keys are unique; changed input on a reused
key is rejected. Failed attempts may leave unused audit snapshots, never a
partially applied operational state.

```sh
# Export tokens and reviewer identity from .env.assessment.example first.
.venv/bin/python -m uvicorn blood_assessment.integration.api:create_app --factory --host 127.0.0.1
```

Open `/docs` for typed request contracts. Endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /assessments` | Validate, forecast, project and persist |
| `GET /assessments/{id}` | Replay persisted assessment and policy |
| `POST /assessments/{id}/agent` | Opt-in SDK review |
| `POST /assessments/{id}/approvals` | Explicit authenticated human decision |
| `POST /assessments/{id}/proposals` | Require matching approval, then preview |

Client routes require `Authorization: Bearer ASSESSMENT_API_TOKEN`; approvals
require a separate `ASSESSMENT_REVIEW_TOKEN`. The reviewer identity comes from
server configuration, not the submitted body. No token means fail closed. This is
a local service authentication boundary, not a complete multi-user identity or
production deployment system. Do not expose it publicly without deployment hardening.
Approval applies only to the immutable snapshot/assessment. A changed policy or
snapshot needs a new approval. Decisions are retained as immutable audit facts;
revocable approval workflows and shipment execution are outside this MVP.

## Aiven / PostgreSQL later

Set `DATABASE_URL` using a psycopg SQLAlchemy URL and the provider's TLS settings,
and `DATA_SCHEMA` to `public` or `kim`. Source tables must use the attached spec's
columns (`sites.type`, `units.storage_site`), not the older `blood_demo` transformed
schema. The adapter opens one **REPEATABLE READ, READ ONLY** transaction for all six
source tables. Schema names come from a fixed allowlist. Configure a read-only
source database role; use a separate audit connection through
`ASSESSMENT_DATABASE_URL`. No migration/import of operational records is run.

```sh
.venv/bin/python -m blood_assessment.demo --postgresql --output runs/postgres-demo
```

Real PostgreSQL connectivity and source facts remain unverified until credentials
and tables are available. CI tests the adapter's transaction/read-only contract
with a mocked connection; this is not a real PostgreSQL integration test.

## Graph optimizer

The default approval-gated path now uses `blood_assessment/optimization/`.
See [model, constraints, dated requirements, graph endpoints and measured results](GRAPH_OPTIMIZER.md).
The optional `Optimizer.solve` aggregate plugin contract remains for custom developer integrations.

## Verification

See the implementation report for the final test counts and blockers. The suite
covers ledger reconciliation, partial days, verified sparse zeros, whole-date
folds, no future feature leakage, pooled ML on separately labeled synthetic data,
unknown plans, floor policy, FEFO/expiry boundaries, no assumed arrivals, exact
blood groups, idempotency, approval isolation, malformed/provider failures, API
authentication and source preservation. The live-agent test is opt-in.
