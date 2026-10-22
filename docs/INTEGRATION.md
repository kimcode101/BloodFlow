# Shared model, source reconciliation and setup

## Product goal

The demo should help a coordinator see a potential local shortage, inspect the supporting evidence, and review a feasible response. It needs four things: a usable inventory, an estimate of demand, routes for replenishment, and timely public information. Social reports can trigger verification. They do not establish patient injury severity, transfusion need, blood group, or shortage size.

This remains a synthetic hackathon model. Real facility names are present, but the supplied capacities, clinical labels, blood counts, routes and thresholds are unverified demo assumptions. No production medical record or live stock feed is connected.

## Authoritative sources

The six-file team bundle is the active scenario. Its 1,538 units include 777 available and 761 used units. All 981 historical transfer references and movement chains reconcile. Daily usage totals exactly match the used-unit ledger. `sites.csv` defines H1–H4, B1–B2 and external supplier X1.

The earlier `blood_storage.csv` represents another synthetic scenario: 3,324 records and 662 available units. Numeric IDs 2394, 2977 and 2979 collide with the new file but disagree in blood group or dates. Adding the two files would double-count inventory and mix independent histories. The old file is retained byte-for-byte in `data/raw/legacy_stock/`; a normalized alternative is in `data/alternatives/legacy_units.csv`. It is excluded from the active ledger.

Both original Python scripts are retained byte-for-byte in `data/raw/original_scripts/`. The familiar filenames in `blood-storage/` now delegate to the shared module instead of implementing a second data model. No file in the user's original source location is edited.

Source SHA-256 hashes are in `data/integration_report.json`. Git treats raw files as binary to preserve their exact bytes across operating systems. Rebuild canonical data with `python tools/build_dataset.py`; check it with `python -m blood_response validate`.

## One data contract

All canonical CSVs are UTF-8 without a BOM, with LF line endings and explicit headers. Dates use `YYYY-MM-DD`. Timestamps include an offset and use Europe/Paris, including the 25 October DST change. CSV booleans are `true` or `false`. Empty numeric/date cells mean unknown or not applicable, never a measured zero. Counts are integer red-cell units. Blood groups retain `+` and `-`.

| File | Row grain and key | Important meaning |
|---|---|---|
| `sites.csv` | One site, `site_id` | `site_type` is hospital, blood_bank, or external. Hospital `home_bank_id` is a bank reference. Clinical capacities are fixture metadata, not validated allocation rules. |
| `units.csv` | One physical demo unit, `unit_id` | `UNIT-00002394` is namespaced; `source_unit_id` retains 2394. `site_id` is current/final location. `initial_site_id` is the earliest known location in the provided movement history, not a claim about collection origin. |
| `transfers.csv` | One completed historical unit movement, `transfer_id` | References one unit and two sites. Only a date was supplied; no departure time, arrival time, or future shipment promise is invented. Same-day source transfer order is retained. |
| `daily_usage.csv` | One date/site/group, composite key | Reconciles to the unit ledger. Missing combinations within the supplied coverage become explicit zero rows with provenance. The current partial day is labelled and excluded from averages. |
| `planned_activity.csv` | One scheduled procedure, `activity_id` | `units_expected` is expected demand, not stock reserved or already consumed. `scheduled_critical` is distinct from `elective`. No patient identity is included. |
| `travel_times.csv` | One directed site pair | 30 internal estimates are preserved. The 12 external pairs have `route_status=unavailable` and blank distances/times. Unknown ETAs cannot support a transfer proposal. |
| `site_aliases.csv` | One legacy name mapping | Maps Crozatier→B1, Cabanel→B2 and the four source hospital names to stable site IDs. Do not join on free-text names. |
| `social_reports.jsonl` | One synthetic report, `report_id` | Forward demo only. The report's publication/availability timestamps control when it may enter a model request. Template dates are provenance only. |
| `scenario.json` | One versioned scenario | Authoritative clock, thresholds and explicit modelling assumptions. |

Source-only derived fields such as `days_to_expiry` and `expiring_soon` are recalculated from expiry date and the scenario clock. They are not copied as permanently valid inventory attributes.

## Aligned scenarios and clocks

The operational snapshot is dated **22 October 2026**, with partial-day usage. The exact time was not supplied. The demo explicitly assumes noon in Paris as its starting clock. The historical demand window is 16–22 October, but only the six complete days, 16–21 October, contribute to the starting baseline. Planning coverage runs from 23 October through 5 November.

The original social fixture covers 16–18 October. Joining a 22 October inventory snapshot into that earlier replay would leak future information. The original fixture and its measured API results remain unchanged. For a coherent forward demo, `data/canonical/social_reports.jsonl` shifts the invented template by seven local calendar days to **23–25 October**. Its timezone offset correctly changes from +02:00 to +01:00 on Sunday. These are hypothetical demo posts, not reports of real protests on those dates.

The forward scenario has not been run through the Decisions API. Existing agreement scores apply only to the unchanged original replay. A future live run can use:

```sh
python run_decisions_replay.py --dataset data/canonical --run-dir runs/forward-social
```

That command requires the team's own OpenAI API credential and makes paid calls. Raw posts have no expected flag or oracle event ID. The reference decisions remain separate and assistant-authored, with no independent human validation.

The shared social handoff policy is implemented separately from inference. It suppresses exact reposts, ensures that an urgent report raises its selected event's review priority, preserves unresolved priority through repeated/old reports, and separates `event_phase` from `evidence_status`. It does not merge ambiguous model-selected events automatically. To postprocess the recorded historical outputs without making new API calls:

```sh
python -m blood_response normalize-social --reports paris-protest-social-simulation-v1/social_reports.jsonl --predictions openai-decisions-replay-v1/baseline/predictions.json --output runs/historical-policy-handoff.json
```

Historical responses are rejected if paired with forward-scenario timestamps. This produces a deterministic application-policy handoff, not a new model benchmark. The measured baseline files and scores remain unchanged.

## Demand and stock logic

- Historical baseline: mean units per hospital and group over observed complete days in the preceding seven-day window. Include genuine zeros. Exclude partial days. Missing coverage remains unknown.
- Planned activity: sum procedures by planning date, hospital and group.
- Forecast: `ceil(max(full-day baseline, planned activity))` for each hospital/group. This provisional planning-floor rule avoids adding an entire baseline to scheduled work that it may already include. It is explicit, testable and replaceable; it is not a validated forecasting model.
- Usable stock: status available and expiry strictly after the service date. Every blood group is represented even at zero stock. Zero stock is CRITICAL; positive stock without a usable demand estimate is UNKNOWN.
- Transfers: exact blood-group match, home bank to hospital, earliest expiry first. Share and decrement each bank's candidate unit pool, so one unit cannot be proposed to two hospitals. Retain one baseline day at the bank. Prioritize scheduled-critical shortfalls, then larger deficits. Only provided routes that fit the planning day are eligible. Proposals do not execute movements.
- Social signal: supports review priority and contextual investigation. No coefficient translating a protest, crowd size or post score into blood units is invented. A coarse zone-to-facility candidate map is marked as a demo assumption, not patient routing. Fictional social institutions are not silently equated with real-named hospitals.

At the starting snapshot the planner estimates 140 units for 23 October under this rule, including 68 units of scheduled activity. It proposes three reviewed transfers totalling 15 units and leaves no uncovered units under its stated reserve and routing assumptions. This is a model result, not evidence of real demand or actual transfer availability.

## Simulation

`python -m blood_response simulate` works offline and leaves canonical inputs unchanged. It writes a new state and tick log under `runs/`. It refuses to overwrite an existing output directory. A seed and the tick index make reruns reproducible.

Each tick advances one real elapsed simulated hour. Consumption is assigned to the interval's starting calendar day. Expiry is applied again at the ending date boundary. This handles midnight and the autumn DST transition. Usage and movement ledgers are updated with every consumed unit, and inventory conservation is checked after every tick.

The donation scenario retains the original contributor's ratios: expected inflow equals demand except O-negative, where the ratio is 0.6. These are generated scenario arrivals, not confirmed donations. New donations become usable immediately; donor processing, testing, crossmatching, clinical compatibility, transport queues and patient triage are outside this simplified model. Bank-to-hospital use is allowed within a tick only when the supplied rush-hour ETA fits that hour. Emergency consumption can use a bank's reserve; the reserve constrains proposals, not actual simulated use.

## Gaps and resolutions

| Issue | Resolution |
|---|---|
| Two incompatible inventories and colliding IDs | Choose the reconciled bundle as canonical; preserve the older source as an isolated, namespaced alternative. |
| Names versus H/B site IDs | Add explicit alias mapping; use IDs in every canonical relationship. |
| Original hardcoded hospital demand totals 64/day versus registry metadata 125/day | Remove the parallel hardcoded model. Use observed full-day usage for the simulator/planner; retain registry averages as unverified metadata. The starting observed aggregate baseline is about 114.33/day. |
| Social weekend predates stock snapshot | Keep historical replay separate; declare and generate a hypothetical forward social scenario. |
| Different date/boolean encodings and stale derived expiry columns | Normalize dates/booleans; calculate expiry from the simulated clock. |
| Sparse usage groups | Add 61 explicit zero rows only after reconciling the supplied unit ledger. Do not fill dates outside coverage. |
| Partial-day usage would distort daily averages | Exclude partial days and expose missing demand as unknown. |
| Shared bank inventory could be counted once per hospital | Allocate from a single declining unit pool with a declared reserve. |
| External transfers have no route estimates | Preserve completed history; represent missing ETAs explicitly and exclude unsupported new proposals. |
| Missing usage could appear OK; empty groups could disappear | Separate UNKNOWN from CRITICAL and keep zero-stock groups in summaries. |
| Loader silently replaces tables and depends on working directory | Use repository-relative paths, a dedicated schema, transactional load and explicit --reset. |
| “Simulated hours” originally left expiry on wall-clock dates | Advance an explicit, persisted Paris clock and reconcile expiry/usage each tick. |
| No unified setup or shared checks | One CLI, documented dependencies, reproducible builder, tests and PR checks. |
| Independent model answers could escalate a duplicate or leave an urgent event on MONITOR | Enforce the application policy in code; separate event lifecycle from evidence status. Preserve the observed baseline for comparison. |

## Evidence that is still absent

The files do not contain patient-level emergency requests, validated hospital catchments, real compatibility constraints, road closures mapped to routes, verified external ETAs, confirmed future blood receipts, or clinical social-to-demand conversion parameters. Those cannot be recovered by renaming columns. The application keeps them unknown or outside scope rather than manufacturing facts. This contribution does not claim to validate the medical model.

Optional PostgreSQL commands have not been executed against a real Aiven database in this integration task. Offline data validation, deterministic simulation, planning and regression tests are run locally. See the PR validation results for the exact checks.
