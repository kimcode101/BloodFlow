# Paris protest social simulation — starter dataset v1

**36 invented French social posts, 12 per day, 16–18 October 2026.** Prepared 22 October 2026. This is a small, authored, historically inspired hackathon fixture. It contains no authentic scraped posts and no patient or inventory records.

## Open first

Read `TIMELINE.md` to inspect all posts and expected flags. Read `RESEARCH.md` for the evidence boundary and source links.

## Files

| File | Purpose | Send to decision model? |
|---|---|---|
| social_reports.jsonl | Raw synthetic incoming posts and source metadata | One current row, plus earlier context only |
| decision_rubric.json | Six per-report questions, comparison guidance and action policy | Instructions only; adapt to the provider's schema |
| expected_decisions.jsonl | Authored decisions, tags, event links and rationales | No: evaluation targets |
| expected_event_updates.jsonl | Authored event views after each linked report | No: reference replay only |
| scenario_catalog.json | Scenario provenance, event families and integration boundary | No: reference metadata |
| research_sources.json / RESEARCH.md | Researched anchors and limitations | No: do not inject hindsight |
| TIMELINE.md | Human-readable review view | No: contains labels |
| validate_dataset.py | Offline structural/chronological validation | No API calls |

`is_synthetic` and `publisher_identity_authenticated_in_simulation` describe the exercise. Every account ID begins SIM-. The authentication field is trusted fictional source metadata; it does not mean a real account exists. All severity values describe a report's claim. The labels never establish clinical severity or transfusion requirements.

## Minimal implementation

1. Replay raw reports in `available_at` order. Use that as the simulated clock. Each report becomes available one minute after its invented publication time.
2. Ask the six independent questions against the current post. Keep unknown when information is missing. Retain the raw report for inspection; the decision API is not asked to generate a free-text explanation.
3. Compare relevant content to a few previous active events, using only prior available reports. First decide same/different/unclear; then assess its contribution. Explicit repost links help suppress duplicate evidence.
4. Apply the action policy in code. IGNORE means no new Paris alert, not delete. A Lyon incident can be severe while staying outside the Paris alert queue.
5. Present event-level review priority with the underlying reports. Duplicate, weaker or historical reports must not automatically lower an unresolved event's priority. A resolution claim goes through REVIEW; this fixture does not automatically authorise closure.

Stage-two `comparison` labels refer to the prior event context. They cannot always be inferred from an isolated post. Exact duplicate relationships and their transitive original source should be checked before treating accounts as independent. Event snapshots include `action_route`: a high-priority Lyon event remains in its regional route and must not enter the Paris queue. The named Paris zones are coarse demo groupings, not administrative boundaries or hospital catchment areas; `paris_west` includes the Opera/Concorde/Etoile central-to-western corridor for this fixture.

## Important demonstrations

- SOC-002 → SOC-016 → SOC-017: preparation becomes an injury claim needing urgent verification.
- SOC-017 → SOC-018 → SOC-019: a repost adds no evidence; separate medical attendance supports only part of the claim.
- SOC-024 → SOC-025: contrary evidence and old footage do not silently clear or refresh an unresolved event.
- SOC-008 / SOC-020 versus SOC-017: a northern-Paris gathering stays distinct from République.
- SOC-010 → SOC-011 → SOC-028: an invented hospital appeal is disputed and later recirculates.
- SOC-014 → SOC-023 versus SOC-021: general transport context differs from an explicit fictional donor-access interruption.
- SOC-015: high-severity Lyon content must not trigger a Paris hospital alert.
- SOC-027 / SOC-029 / SOC-032: local resolution reports are reviewable updates, not a citywide medical all-clear.
- SOC-034: severe content with unknown location and time remains unmatched.

## Separate datasets and integration

Keep patient requirements and blood storage separate. The social component can eventually emit `event_id`, `zone`, `as_of`, `impact_pathway`, evidence status and review priority, with supporting report IDs. A later component can compare those signals with hospital demand and stock. This package predicts neither casualties nor blood units and assumes no patient-to-hospital routing.

## Validation and limits

Run `python validate_dataset.py` from this folder. It verifies counts, IDs, enums, chronology, quotations, prior-only comparison links and event references. These are structural checks, not proof that every authored label is correct. The fixture has no real-world class prevalence, no calibrated thresholds, no weather/transport model, and no measured forecasting value. Review the rubric and labels with your team. French language and ambiguity handling should be tested explicitly when calling a model.

The reference fixture was authored before the live API replay. Its expected labels are not API outputs; see the sibling `openai-decisions-replay-v1` folder for observed results. No model probabilities are fabricated. Compare actual API outputs with the reference labels, inspect disagreements, and split whole event families if you later expand this into a benchmark.
