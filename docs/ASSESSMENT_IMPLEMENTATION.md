# BloodFlow implementation and verification — 22 October 2026

The forecasting system, executable SQL/math data agent, and approval-gated graph
optimizer are implemented in `blood_assessment/` in the desktop repository.

| Component | Current implementation |
|---|---|
| Data | Validated immutable CSV/PostgreSQL snapshots; source reads only |
| Forecasting | Three baselines, pooled shrinkage, pooled Poisson candidate, whole-date backtesting |
| Inventory | Partial-day scenario, scheduled-demand floor/stress, FEFO projections, expiry and targets |
| Data agent | Actual SQL, forecast, backtest and projection function tools; checked numerical evidence |
| Graph optimizer | Dated CP-SAT allocation adapted from the other project; default proposal engine |
| Constraints | Eight groups, explicit reserves, route/timing eligibility, whole units, dated expiry |
| Decisions | Proposed dated requirements and group priorities, explicit approval, hypothetical transfers |
| Persistence | Snapshots, forecasts, tool receipts, agent runs, approvals and full graph results |
| API | Assessment, agent, approval, proposal, result replay and graph JSON endpoints |
| Demo | Reproducible base/stress scenarios with separate approvals and unchanged source data |

## Final verification

**91 passed, 2 skipped** on Python 3.14.4 with OR-Tools 9.15.6755. Both skips are
opt-in live OpenAI tests. A harmless joblib warning falls back from unavailable
physical-core detection to logical cores. Exact packages are frozen in
`requirements-assessment.lock.txt`.

The actual SDK runner and Python function tools were tested with scripted model
responses; this is not a live LLM result. The graph suite independently enumerates
a small network to verify the exact objective optimum, and exercises priorities,
dates, expiry, reserves, route exclusions, solver failures, reproducibility,
approval-gated persistence and authenticated graph retrieval.

The offline graph demo proved all four objective stages optimal:

| Scenario | Requirements | Met | Unmet | Local assigned | Proposed inbound |
|---|---:|---:|---:|---:|---:|
| Floor baseline | 317 | 317 | 0 | 130 | 187 |
| Additive stress | 400 | 393 | 7 | 130 | 263 |

These requirements include an explicit planning buffer; they are not observed
clinical consumption. Source inventory/history is unchanged. No transfers execute.
The source `hackathon` project was inspected and adapted without modification.

## Remaining external connections and scope

- **Aiven:** not connected; source facts are CSV-verified. The read-only PostgreSQL
  adapter exists, but real database integration requires connection settings/tables.
- **Live OpenAI:** no locally configured replacement credential/model was available.
  No live call or live-model quality claim is made.
- **Exploratory agent scenarios:** promoting a data-agent receipt into a new formal
  requirement assessment remains a separate controlled workflow. The standard
  deterministic assessment → approval → graph path works now.
- **Interface/chatbot:** requested next; this graph implementation exposes the API
  and graph JSON needed for that interface.

For setup and numerical assumptions, see `ASSESSMENT.md`. For executable agent
tools, see `DATA_AGENT.md`. For graph equations, timing conventions, provenance,
API contracts and reproduction, see `GRAPH_OPTIMIZER.md`.
