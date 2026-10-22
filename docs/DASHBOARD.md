# BloodFlow local dashboard

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-assessment.lock.txt
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python -m blood_assessment.dashboard
```

Open http://127.0.0.1:8765. Use `--port 8766` if needed. The Python process serves both the compiled UI and its API. The standalone Vite development server does not proxy the authenticated API; rebuild for integrated testing.

The dashboard uses the bundled synthetic CSV snapshot at 22 October 2026, noon Paris. It does not connect to Aiven. Baseline and additive stress each have their own assessment and explicit review dialog. Clicking **Approve & calculate proposals** stores a local demo approval and invokes the actual CP-SAT solver. Saved approved plans survive reloads. Nothing executes shipments or edits operational tables.

The blood-group filter affects the network and transfer table; headline metrics summarize the whole scenario. The network is schematic. Expand Unit IDs for exact allocation evidence.

**Ask BloodFlow** defaults to deterministic evidence retrieval: hospital/group stock and target, policy differences, reserves and solver objectives. It is clearly labeled offline and supports single-turn questions, not conversational memory. Unsupported questions show its limits and default H1 O- evidence. Chat answers, citations and tool activity are audited separately.

To enable live investigation, configure a replacement `OPENAI_API_KEY` and `OPENAI_MODEL` in the server environment before starting the dashboard. Never commit credentials or paste keys into the page. The live toggle invokes the existing Agents SDK data analyst with read-only snapshot SQL and forecasting/projection tools; numerical claims are checked against receipts. Saved-plan explanations remain deterministic and are displayed alongside the validated live analysis. Live calls are bounded and cannot approve or execute transfers. No live OpenAI call was made during dashboard verification.

Audit data is stored in `runs/dashboard/audit.sqlite`, separate from the CSVs. The local UI uses an HttpOnly SameSite cookie, same-origin POST checks and a localhost host allowlist. The launcher binds exclusively to 127.0.0.1. This is a single-user local demo, not a production multi-user reviewer authentication service. The existing bearer-token FastAPI API remains separate.

Verification: production frontend build; backend approval, idempotency, session/origin, host, evidence and unavailable-live-model tests; full Python suite; browser baseline approval, group filtering, stress selection, chat, desktop and mobile layout.

Design fidelity: retained navy rail, white main canvas, burgundy action, teal flow lines, four-metric band, and pale assistant panel from the generated concept. Intentional differences: real allocation rows and actual route topology replace illustrative data; unapproved scenarios show blank results; mobile stacks chat below the plan.

## Generate test inputs

Use **Generate test scenario** to add a demand surge, new available donations, or both to an independent copy of the original fixture. The panel lists changes and a reproducible seed. Assessments are recalculated immediately; optimization still requires explicit review. **Reset to original** restores the original scenario without deleting audit records. Changing floor/stress policy also returns to the original fixture; generate again under that policy if needed.

Each click starts from the original CSV snapshot, not the previous generated scenario. Used-unit history, daily usage, transfers and source files are preserved. New unit/activity IDs are synthetic. This simulates inputs at the fixed snapshot date; it is not a live news feed or advancing clock. Model chat uses the selected generated snapshot.

For replay, POST `/ui/simulate` with `{ "kind": "mixed", "seed": 42, "planning": "floor" }` using the same local session/origin boundary. Repeating the same inputs retrieves the same assessment and any previously approved plan. Saved generated assessments can be fetched through `/ui/state?assessment_id=...` even after restart. A new random seed creates an unapproved assessment.
