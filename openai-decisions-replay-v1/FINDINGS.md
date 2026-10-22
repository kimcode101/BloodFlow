# What the live Decisions API run showed

**All 36 posts were replayed through OpenAI's direct Decisions API using `gpt-6-luna`. Report flags agreed with the original expectations on 32/36 posts (88.9%).** The original expected labels and raw posts remain unchanged.

[Open the 36-case report](report.html) · [Read every chronological flag and disagreement](COMPARISON.md)

## What was actually run

One chronological replay, three requests per post, 108 successful requests. Each post was assessed, matched to a prior model-built event or a new event, and then given a report flag plus event priority/status. There were no oracle event IDs or expected decisions in the inference requests. Previous model decisions were allowed to affect later event handling. All requests, native responses, model identity, usage, and API request IDs are saved in `baseline/calls/`.

The run used 392,724 input tokens. At the published base input rate of $0.10 per million, that is **$0.0392724 (about four US cents)**. This is a usage-based estimate, not an account billing receipt; regional or other premiums are unknown. The sum of the 108 successful request latencies is 57.263499 seconds; that is not the total time spent setting up, reviewing, or packaging the run.

## Scores and their meaning

| Comparison | Agreement |
|---|---:|
| New-report action flag | 32/36 (88.9%) |
| Event review priority after the post | 22/33 (66.7%) |
| Contribution: new, duplicate, adds information, etc. | 27/36 (75.0%) |
| Coarse location | 30/36 (83.3%) |
| Event status label | 18/33 (54.5%) |

An always-IGNORE baseline agrees on 16/36 (44.4%). This is not a balanced clinical benchmark. The expected labels were assistant-authored in the earlier conversation and have not been independently reviewed. Agreement is not accuracy. Reports within an event are correlated, and there was only one run.

Across all report pairs, the model linked 43 of the 56 pairs that the authored references place in the same event. It made no cross-event merges under that reference grouping (pair precision 43/43; recall 43/56). It sometimes split one authored event into several model events or left a report without an event. These figures evaluate the reference's definition of an event; they do not establish that every split is wrong.

## The four report-flag disagreements

| Post | Expected | API | Interpretation |
|---|---|---|---|
| SOC-010: forwarded urgent appeal from a fictional hospital | URGENT_REVIEW | REVIEW | API marked timing unknown. The forwarded message has no explicit incident time, so REVIEW is defensible under the unknown-time rule. Resolve this rubric ambiguity before calling it an error. |
| SOC-018: exact repost of the serious-injury report | IGNORE | URGENT_REVIEW | It selected duplicate and gave DUPLICATE probability 0.93, yet selected a fresh urgent flag. This is an internal decision inconsistency under the stated duplicate-suppression policy. |
| SOC-022: a mild fainting episode reported as over | IGNORE | REVIEW | API treated it as a resolution to review. The reference intends resolution of the small medical episode, not closure of the entire protest. Define the scope of resolution. |
| SOC-033: municipal cleanup update | IGNORE | REVIEW | It found no medical pathway and selected NO_EVENT, yet requested review. This is over-escalation relative to the authored policy. It also inferred a specific Paris zone not stated in the post. |

## How the République thread evolved

| Time, Europe/Paris | New information | API report flag | API event result |
|---|---|---|---|
| Fri 09:11, SOC-002 | Planned gathering | MONITOR | Creates MODEL-EV-002; MONITOR / planned. |
| Sat 12:01, SOC-016 | Tension, no injuries seen | MONITOR | Same event; MONITOR / active. |
| Sat 12:06, SOC-017 | Apparently serious injuries | URGENT_REVIEW | Same event, but event priority stays MONITOR. Report and event priority are inconsistent. |
| Sat 12:08, SOC-018 | Exact repost | URGENT_REVIEW | Recognises duplicate; event becomes URGENT_REVIEW. It should not need a repost to raise event priority. |
| Sat 12:16, SOC-019 | Separate reporter sees medical attendance, severity unknown | REVIEW | Creates MODEL-EV-011 instead of updating the earlier thread. A broad gathering-level grouping would link these; an incident-level grouping could reasonably separate them. |
| Sat 18:01, SOC-024 | Incomplete account disputes serious injuries | REVIEW | Returns to MODEL-EV-002, retains URGENT_REVIEW, but calls the contribution adds_information and status active. |
| Sun 08:01, SOC-025 | Explicitly old footage | IGNORE | Links to prior event and retains unresolved URGENT_REVIEW. |
| Sun 09:01, SOC-027 | Local intervention reported closed | REVIEW | Same event; REVIEW / resolution_reported. |

## What worked

- Lyon's serious-injury report, SOC-015, did not trigger a Paris alert. It received a separate event with urgent regional review priority.
- The northern-Paris gathering remained separate from République.
- The hospital denial was linked to the appeal, and its later recirculation was ignored as a new trigger.
- Explicit old Sunday footage was linked to the Saturday event without creating a fresh incident.
- General metro restrictions remained transport context rather than becoming a claim about blood-delivery failure.

## Workflow and reference limits exposed by the run

1. **Questions in one request are independent.** The contribution, report flag and event priority questions cannot consume each other's answers in that same request. The event-priority question also did not include the full current-report severity/action mapping. The inconsistent priorities are a finding about this prompt/workflow, not proof of an inherent model limitation. Use the model for atomic judgments, then enforce duplicate suppression and escalation consistency in code, or add another dependent decision call.
2. **Lifecycle and evidence are mixed in one status field.** A protest can be active and its injury claim disputed. Strictly comparing active against disputed marks two compatible descriptions as different. Split `event_phase` from `evidence_status` before treating this metric as meaningful correctness.
3. **Some location references assume knowledge not present in the post.** The invented collection-site name Démo-Nord does not itself establish a Paris address. Supply a small site/account-to-location registry or annotate unknown. The model's unknown location on SOC-009/SOC-021 is not necessarily an error. Its specific western-Paris choice on SOC-029 is unsupported by that report.
4. **Evidence labels overlap.** A rumour forwarded from a friend is also an attributed report. Define precedence or separate first-hand/second-hand from verified/unverified.
5. **Reference tag lists are not exhaustive negative annotations.** Absence of UNVERIFIED does not reliably mean verified. The tag agreement figures in raw summary data are descriptive only, particularly the low UNVERIFIED match rate. Do not call them tag accuracy.
6. **No outcome validation.** This test measures report triage and event handling only. It establishes neither blood-demand forecasting value nor operational safety.

## Suggested next iteration

Keep the 36-case baseline frozen. Clarify event grouping, timestamps and the few disputed labels. Add the small fictional site-location lookup. Move the action policy and event-priority consistency rules into ordinary code. Then run the same cases again as a named second version and compare the traces. No second version or extra API run was performed here.
