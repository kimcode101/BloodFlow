# Paris blood-response hackathon

**Integrated graph optimizer:** [dated CP-SAT model, approval flow, and reproducible results](docs/GRAPH_OPTIMIZER.md). Graph allocation is now the default proposal engine.

**SQL and math data agent:** [executable tools, SDK loop, and live setup](docs/DATA_AGENT.md). The agent can query a read-only snapshot and invoke forecasting/projection functions on demand.

**Forecasting and assessment:** [setup, methods, approval API, and demo](docs/ASSESSMENT.md). The new `blood_assessment` package reads source data without mutating operational records. Aiven is optional; the offline forecasting and graph-optimization demo works now.

**Current integrated demo:** [data contract and setup](docs/INTEGRATION.md). The active dataset combines stock, historical use, planned activities, site metadata and travel estimates. The social component supplies evidence to assess, not an automatic conversion from posts into transfusion units.

```sh
python -m pip install -r requirements.txt
python tools/build_dataset.py
python -m blood_response validate
python -m blood_response plan --output runs/next-day-plan.json
python -m blood_response simulate --ticks 84 --seed 42 --output runs/weekend-demo
python -m unittest discover -s tests -v
```

These commands work offline after installing timezone data; the simulation writes only to the selected new run directory. [PostgreSQL setup](blood-storage/README.md) is optional and requires explicit database commands. Every supplied source is preserved under `data/raw/`; the six related CSVs form the active ledger. The earlier stock fixture is an alternative, not additional inventory.

See [gaps and resolutions](docs/INTEGRATION.md#gaps-and-resolutions), [the machine-readable validation report](data/integration_report.json), and [the canonical CSVs](data/canonical).

## Original social-only baseline

A small hackathon dataset and chronological replay using OpenAI's Decisions API. The social component flags reports that could matter to blood-service planning. Patient requirements and blood storage belong to separate datasets.

**All 36 social posts, accounts, exact posting times, local injury claims, and blood-service consequences are synthetic.** Real reporting informed the setting for 16–18 October 2026. This is not a reconstruction of verified casualties, a record of real blood shortages, or a clinical system.

## Start here

- [Synthetic Friday–Sunday timeline](paris-protest-social-simulation-v1/TIMELINE.md)
- [What the live API run showed](openai-decisions-replay-v1/FINDINGS.md)
- [Every incoming post: expected and actual flags](openai-decisions-replay-v1/COMPARISON.md)
- [Decision rubric](paris-protest-social-simulation-v1/decision_rubric.json)
- [Research sources and limits](paris-protest-social-simulation-v1/RESEARCH.md)

## Recorded result

One chronological trajectory: 36 posts, three requests per post, 108 successful Decisions API requests using `gpt-6-luna`.

| Comparison | Agreement with the authored reference |
|---|---:|
| Report action flag | 32/36 (88.9%) |
| Event priority after each linked post | 22/33 (66.7%) |
| New information / duplicate / correction classification | 27/36 (75.0%) |

The expected labels were assistant-authored and have not been independently reviewed. These are agreement figures, not clinical accuracy. The [findings](openai-decisions-replay-v1/FINDINGS.md) explain ambiguous labels and inconsistencies exposed by the run. No expected labels or future reports were included in the inference evidence.

The run consumed 392,724 input tokens. At the documented base rate, the input-cost estimate was about USD 0.04; this is not a billing receipt.

## Run locally

Python 3.12 was used. The original social replay scripts use only the Python standard library. The integrated demo also installs timezone data from the root requirements file.

```sh
git clone https://github.com/benlewis-beyondthought/paris-blood-social-simulation.git
cd paris-blood-social-simulation
python paris-protest-social-simulation-v1/validate_dataset.py
python run_decisions_replay.py --self-test
```

To make a fresh live run:

```sh
python run_decisions_replay.py --run-dir runs/my-replay
```

Provide your own OpenAI API key at the hidden prompt, or set `OPENAI_API_KEY` in your process environment. The runner does not automatically load `.env` files. No key is included in this repository. Live runs use the direct Decisions API and can incur charges. They do not change the frozen baseline included here.

The new run writes a chronological `COMPARISON.md`, machine-readable scores, model-built event histories, and request/response receipts under the chosen run directory. A cached run can resume only when its dataset, rubric, runner and model fingerprints match.

## Repository contents

```text
run_decisions_replay.py                  # Live replay and comparison runner
paris-protest-social-simulation-v1/      # Inputs, expected labels, rubric, source notes
openai-decisions-replay-v1/              # Frozen observed baseline and findings
  baseline/calls/                       # API requests and responses; no auth headers
  baseline/traces/                      # Per-post evidence and output traces
```

The generated `report.html` can be downloaded and opened locally. GitHub's file view does not run the report's HTML. The Markdown comparison works directly in GitHub.

## Scope of the recorded baseline

This component emits event locations, evidence assessments and review priorities. It does not predict transfusion units, assign patients to hospitals, or read actual blood inventories. Keep the baseline frozen while reviewing event grouping, timing ambiguity, source geography, and the distinction between lifecycle and evidence status.

The recorded run leaves duplicate suppression and escalation to the model so their inconsistencies remain visible. The integrated demo now provides a separate deterministic handoff policy in `blood_response/social.py`. See the integration guide for an offline comparison command. That postprocessing does not change the baseline or count as a new API run.


## Local dashboard and evidence chat

Build `frontend` with `npm ci && npm run build`, then run
`python -m blood_assessment.dashboard` from the repository root using the assessment environment.
Open http://127.0.0.1:8765. Review and approve a demo scenario to calculate transfers,
filter by blood group, inspect allocated unit IDs, and ask about the saved evidence.
See [dashboard setup and limitations](docs/DASHBOARD.md).
