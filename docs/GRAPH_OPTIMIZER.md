# Integrated dated graph optimizer

BloodFlow now uses the graph optimizer by default after explicit approval. The
implementation adapts the user's `hackathon/backend/optimizer/solver.py`: integer
OR-Tools CP-SAT, canonical variable ordering, one worker, seed zero, exact objective
locks between proved optimal stages, and retained valid incumbents on later-stage
failure. Source-file SHA-256 hashes are in `optimization/provenance.json`.
The other project is unchanged; its web backend and database were not copied.

## What changed

The earlier solver allocated aggregate bank/hospital/group flows using Haversine
costs. The integrated solver allocates **expiry cohorts to dated hospital/group
requirements**, then assigns concrete unit IDs. It uses the supplied road-factor
travel distances and explicitly available routes. Hospital/group priorities remain
separate; they are not collapsed into a hospital-wide score.

The existing API `POST /assessments/{id}/proposals` now calls this solver after
verifying the approval belongs to that exact assessment. It returns:

- Solver status, all objective-stage outcomes, runtime and OR-Tools version.
- Proposed bank → hospital transfers with blood group, integer quantity and unit IDs.
- Dated unit assignments, met requirements and unmet requirements.
- Graph nodes, allowed/blocked connections and positive transfer edges.
- Complete solver inputs, their hash, snapshot ID, assessment ID and approval ID.

Read a persisted result at `GET /optimization/{run_id}` and graph JSON at
`GET /optimization/{run_id}/graph`. Both require the existing API bearer token.
Generating a proposal never executes a shipment or changes stock/history.

## Requirements and timing

Assessment construction now stores the daily breakdown alongside each proposed
target. For daily planning quantities p[d] and configured buffer b:

`cumulative[d] = ceil(sum(p[1:d]) * (1+b))`

`dated_units[d] = cumulative[d] - cumulative[d-1]`

This preserves the original approved whole-unit target exactly, while avoiding
rounding every daily forecast independently. These units include a planning buffer;
they represent reserved planning capacity, not predicted clinical consumption.
The selected floor or additive-stress policy remains visible in the assessment.

Older assessments without this dated breakdown must be reassessed and approved
again. The solver rejects them rather than silently inventing an unapproved schedule.
The old aggregate custom-solver interface remains optional for developer injection;
the ordinary API and demo use the dated implementation.

All proposals form a **single dispatch** after the source snapshot, arriving by
midnight at the start of the first planning day. A route is allowed only if its
configured normal/rush duration fits that interval. Routes with missing duration,
missing/nonpositive distance, or insufficient travel time are excluded with reasons.
Dates use Europe/Paris, with timezone-aware elapsed-time calculation.

There is no claim of exact procedure times, fleet availability, or optimized
multiple-day dispatch scheduling. The midnight demand boundary is an explicit
simulation convention. Existing historical transfers are never future arrivals.
X1 has no implicit supply and is not an eligible donor.

## Inventory and expiry

Available units marked expired at the chosen date are excluded. Hospital units
needed for the explicit remaining-today scenario are set aside FEFO on a copied
snapshot; the scenario quantity is rounded up. Any unmet remaining-today quantity
is reported separately in inputs and is not repaired by tomorrow's shipments.
With no intraday assumption, the future solve is conditional on unchanged stock
until tomorrow, and that limitation is retained.

At each bank/group, configured reserves withhold the freshest eligible units.
Missing reserve configuration is rejected. If eligible stock is less than the
reserve, every eligible unit is withheld and the shortfall is reported. This is
reserve protection at dispatch, not a guarantee that reserves cannot later expire.

A cohort contains units with the same source site, blood group and expiry date.
An assignment can only satisfy a requirement dated strictly **before** expiry.
Local hospital units can satisfy only that hospital's demand. Bank units can use
only permitted bank → hospital edges. Every unit is assigned at most once.
No blood-group substitution or hospital-to-hospital transfer is modeled.

The final output expands cohort quantities into concrete IDs and independently
checks unit uniqueness, expiry, source/group eligibility, routes, transfer/assignment
agreement and demand conservation. Protected units never enter the solver pool.

## Objectives

For integer assigned units x[lot, requirement] and integer unmet units u[requirement]:

1. Minimize `sum((100 + approved_group_priority) * u)`.
2. Holding stage 1 at its proved optimum, minimize earlier-date unmet requirements
   using weight `horizon_length - date_index`.
3. Holding both prior optima, minimize road distance × transferred units.
4. Holding all prior optima, prefer assignments from earlier-expiring cohorts.

Priorities come from the approved deterministic hospital/group policy, never an
unapproved LLM override. Distance is rounded to metres for the integer objective;
reported road unit-kilometres use the supplied distance. Expiry preference is a
final tie-breaker, not a promise to maximize saved units or minimize actual waste.

Each stage has `policy.graph.max_seconds_per_stage` (default 10, maximum 60).
Worst-case solver time is four times that limit. The same pinned solver version
and inputs produce deterministic flows; equivalent optima can change across versions.

- `OPTIMAL`: every requested objective stage is proved optimal.
- `FEASIBLE`: incumbent exists, current stage not proved optimal; later stages stop.
- `FEASIBLE_PREVIOUS_STAGE`: a later stage failed to yield an incumbent; the prior
  valid allocation is retained and its optimality limits are explicit.
- `INFEASIBLE`, `UNKNOWN`, `MODEL_INVALID`: without an incumbent, no proposals or
  invented solution metrics are returned. The attempted run is still auditable.

`policy.graph.allow_unmet_demand=false` requests complete fulfillment; otherwise
shortages are explicit slack variables. All graph configuration is stored with
and approved as part of the assessment policy.

## Reproduce

```sh
.venv/bin/python -m pip install -r requirements-assessment.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python -m blood_assessment.demo --output runs/graph-demo
```

Use a fresh output directory for the new engine rather than reusing a legacy demo's
idempotency keys. Inspect `report.json` and `audit.sqlite` in that directory. The
demo includes base and additive-stress assessments, separate approvals, graph
results and source-preservation checks. Aiven and OpenAI credentials are not needed.

Observed CSV fixture results with the explicit demo reserves, two-day target,
25% buffer and uniform remaining-day scenario:

| Scenario | Approved planning units | Met | Unmet | Local units assigned | Proposed inbound units | Road unit-km |
|---|---:|---:|---:|---:|---:|---:|
| Floor baseline | 317 | 317 | 0 | 130 | 187 | 854.34 |
| Additive stress | 400 | 393 | 7 | 130 | 263 | 1192.36 |

All four stages were proved optimal for both scenarios. These are synthetic
planning results, not observed demand, clinical benefit, or executed shipments.
The graph solver now proposes fourteen O− units from B1 to H1 in both scenarios;
in the stress case some requirements remain unmet. This supersedes the old
home-bank planner's seventeen-unit stress proposal.

## Tests and deployment limits

New tests independently enumerate a small feasible network and compare the exact
four-objective optimum. Other cases verify expiry-dependent assignment, priorities
under scarcity, earlier-date tie breaking, missing routes, no substitution or
hospital transshipment, reserve exclusion, dated-target integrity, solver failures,
reproducibility, approval-gated persistence, and authenticated graph retrieval.

OR-Tools 9.15.6755 was tested on Python 3.14.4; the complete environment is frozen
in `requirements-assessment.lock.txt`. The ranged requirements also support Python
3.11+. The original project's pinned OR-Tools 9.14 could not be assumed for this
Python runtime, so solver version is explicitly recorded in every output.

Aiven remains unconnected. The live data agent still needs local model credentials.
Its exploratory receipt → proposed assessment promotion is a separate integration
step: it cannot bypass the existing approval boundary or silently change this
solver's input requirements.
