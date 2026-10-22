# OpenAI Decisions API: chronological replay

Exploratory agreement with assistant-authored, unreviewed labels; not real-world or clinical accuracy.

**Report flags: 32/36 agree (88.9%).** Majority-class baseline: 44.4%.

Model: `gpt-6-luna`. Calls: 108. Input tokens: 392,724. Published base-rate estimate: $0.039272. This is not a billing receipt.

The API directly selected the report flag and event priority. Expected labels were read only after replay. Events were built from prior model outputs and raw prior posts. There was no oracle event routing. The six core tags use a 0.5 predicate threshold.

| Expected / actual | IGNORE | MONITOR | REVIEW | URGENT_REVIEW |
|---|---:|---:|---:|---:|
| IGNORE | 13 | 0 | 2 | 1 |
| MONITOR | 0 | 9 | 0 | 0 |
| REVIEW | 0 | 0 | 9 | 0 |
| URGENT_REVIEW | 0 | 0 | 1 | 1 |

## Every incoming post

| Time / ID | Expected flag | API flag | API event / contribution | Event priority / state |
|---|---|---|---|---|
| 16 Oct 08:31 / SOC-001 | IGNORE | IGNORE | MODEL-EV-001 / new_event | MONITOR / unverified |
| 16 Oct 09:11 / SOC-002 | MONITOR | MONITOR | MODEL-EV-002 / new_event | MONITOR / planned |
| 16 Oct 09:21 / SOC-003 | IGNORE | IGNORE | MODEL-EV-002 / duplicate | MONITOR / planned |
| 16 Oct 10:01 / SOC-004 | IGNORE | IGNORE | none / unrelated | IGNORE / normal |
| 16 Oct 11:01 / SOC-005 | IGNORE | IGNORE | MODEL-EV-003 / new_event | MONITOR / planned |
| 16 Oct 11:16 / SOC-006 | IGNORE | IGNORE | MODEL-EV-004 / new_event | IGNORE / planned |
| 16 Oct 12:11 / SOC-007 | IGNORE | IGNORE | MODEL-EV-005 / new_event | IGNORE / normal |
| 16 Oct 14:01 / SOC-008 | MONITOR | MONITOR | MODEL-EV-006 / new_event | IGNORE / planned |
| 16 Oct 15:01 / SOC-009 | MONITOR | MONITOR | none / unrelated | IGNORE / normal |
| 16 Oct 17:01 / SOC-010 | URGENT_REVIEW | REVIEW **DISAGREES** | MODEL-EV-007 / new_event | MONITOR / unverified |
| 16 Oct 17:21 / SOC-011 | REVIEW | REVIEW | MODEL-EV-007 / contradicts | REVIEW / disputed |
| 16 Oct 20:11 / SOC-012 | IGNORE | IGNORE | none / unrelated | IGNORE / normal |
| 17 Oct 09:01 / SOC-013 | MONITOR | MONITOR | MODEL-EV-008 / new_event | MONITOR / unverified |
| 17 Oct 10:01 / SOC-014 | MONITOR | MONITOR | MODEL-EV-009 / new_event | MONITOR / normal |
| 17 Oct 11:01 / SOC-015 | IGNORE | IGNORE | MODEL-EV-010 / new_event | URGENT_REVIEW / unverified |
| 17 Oct 12:01 / SOC-016 | MONITOR | MONITOR | MODEL-EV-002 / adds_information | MONITOR / active |
| 17 Oct 12:06 / SOC-017 | URGENT_REVIEW | URGENT_REVIEW | MODEL-EV-002 / adds_information | MONITOR / active |
| 17 Oct 12:08 / SOC-018 | IGNORE | URGENT_REVIEW **DISAGREES** | MODEL-EV-002 / duplicate | URGENT_REVIEW / active |
| 17 Oct 12:16 / SOC-019 | REVIEW | REVIEW | MODEL-EV-011 / new_event | MONITOR / normal |
| 17 Oct 12:31 / SOC-020 | MONITOR | MONITOR | MODEL-EV-006 / adds_information | MONITOR / active |
| 17 Oct 12:41 / SOC-021 | REVIEW | REVIEW | MODEL-EV-012 / new_event | REVIEW / normal |
| 17 Oct 13:11 / SOC-022 | IGNORE | REVIEW **DISAGREES** | MODEL-EV-006 / adds_information | MONITOR / resolution_reported |
| 17 Oct 15:21 / SOC-023 | MONITOR | MONITOR | MODEL-EV-009 / adds_information | MONITOR / normal |
| 17 Oct 18:01 / SOC-024 | REVIEW | REVIEW | MODEL-EV-002 / adds_information | URGENT_REVIEW / active |
| 18 Oct 08:01 / SOC-025 | IGNORE | IGNORE | MODEL-EV-002 / historical_reference | URGENT_REVIEW / disputed |
| 18 Oct 08:31 / SOC-026 | REVIEW | REVIEW | MODEL-EV-006 / resolves | REVIEW / resolution_reported |
| 18 Oct 09:01 / SOC-027 | REVIEW | REVIEW | MODEL-EV-002 / resolves | REVIEW / resolution_reported |
| 18 Oct 09:11 / SOC-028 | IGNORE | IGNORE | MODEL-EV-007 / duplicate | REVIEW / disputed |
| 18 Oct 09:31 / SOC-029 | REVIEW | REVIEW | MODEL-EV-012 / resolves | REVIEW / resolution_reported |
| 18 Oct 10:01 / SOC-030 | IGNORE | IGNORE | MODEL-EV-003 / unrelated | MONITOR / resolution_reported |
| 18 Oct 10:31 / SOC-031 | IGNORE | IGNORE | MODEL-EV-004 / historical_reference | MONITOR / normal |
| 18 Oct 11:01 / SOC-032 | REVIEW | REVIEW | MODEL-EV-009 / resolves | MONITOR / resolution_reported |
| 18 Oct 13:41 / SOC-033 | IGNORE | REVIEW **DISAGREES** | none / unrelated | IGNORE / normal |
| 18 Oct 14:01 / SOC-034 | REVIEW | REVIEW | MODEL-EV-013 / new_event | MONITOR / normal |
| 18 Oct 16:01 / SOC-035 | MONITOR | MONITOR | MODEL-EV-014 / new_event | MONITOR / normal |
| 18 Oct 19:01 / SOC-036 | IGNORE | IGNORE | none / unrelated | IGNORE / normal |

## Flag disagreements

### SOC-010: expected URGENT_REVIEW, API REVIEW

Message reçu d'un ami : urgence sang à l'Hôpital-Démo-01 dans le nord de Paris, ils n'auraient plus rien. Je n'ai pas de source.

Reference rationale: A specific serious claim warrants immediate verification, not acceptance as a shortage.

Other field disagreements: `{"timing": {"expected": "ongoing", "actual": "unknown"}, "evidence_basis": {"expected": "rumour_or_speculation", "actual": "attributed_report"}}`.

### SOC-018: expected IGNORE, API URGENT_REVIEW

Je suis à République, Paris. Plusieurs personnes paraissent sérieusement blessées près de moi. Des gens demandent de laisser passer les secours.

Reference rationale: Do not count a repost as another casualty observation. The event remains urgent for review.

Other field disagreements: `{"evidence_basis": {"expected": "attributed_report", "actual": "direct_observation"}}`.

### SOC-022: expected IGNORE, API REVIEW

La Chapelle : une personne a fait un léger malaise, elle va mieux et repart accompagnée. Je ne signale aucune blessure dans ce message.

Reference rationale: A resolved mild fainting episode does not justify inferring blood demand; the gathering remains monitored.

Other field disagreements: `{"impact_pathway": {"expected": "none", "actual": "potential_demand"}, "reported_impact_level": {"expected": 0, "actual": 1}}`.

### SOC-033: expected IGNORE, API REVIEW

Paris : les équipes municipales nettoient et remettent en état des espaces publics après les dégradations de samedi. Ce point concerne la remise en état, pas un nouvel incident médical.

Reference rationale: A synthetic social summary of Sunday's municipal update, after its observed 13:30 update. Cleanup does not prove a blood shortage or citywide resolution.

Other field disagreements: `{"zone": {"expected": "paris_unspecified", "actual": "paris_centre_east"}, "timing": {"expected": "ongoing", "actual": "past"}, "evidence_basis": {"expected": "attributed_report", "actual": "direct_observation"}}`.

## Limits

This small case set and its labels were generated by the assistant in the earlier conversation, not independently adjudicated. Label disagreements can reflect model errors, ambiguous criteria, or questionable references. Existing references remain unchanged. One run cannot measure repeatability. No patient, inventory, or verified transfusion outcome is part of the scoring.
