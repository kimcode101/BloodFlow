# Evaluation audit — exploratory baseline

- User authorised this existing dataset and comparison against its existing expected decisions. No additional cases, repeated model runs, or model judge were added.
- Dataset: 36 synthetic posts in 12 authored event families; 12 per day. All inputs reviewed in the prior authored timeline; they are not sampled production traffic.
- Labels: assistant-authored, not independently human verified. Existing labels and expected flags remain unchanged.
- Primary grader: exact report-flag agreement. Event-priority and contribution comparisons are secondary. Score-level agreement uses the highest-probability discrete level, not rounding the expected score. Continuous scores and native distributions remain in receipts.
- Oracle/null wiring checks: 36/36 oracle flag agreement, 16/36 constant IGNORE agreement; missing output rejected. These were offline wiring checks and are not recorded as live results.
- Inference: actual `POST https://api.openai.com/v1/decisions`; returned model checked against gpt-6-luna on every call. No fallback provider/model.
- Prior-only context verified across all 108 requests. Expected labels, oracle IDs, source articles and future posts were absent from inference evidence.
- Errors: one initial sandbox DNS failure is retained in baseline/errors.jsonl. Network permission was granted, and all 108 live requests subsequently succeeded. This setup failure is not scored as a wrong prediction.
- Native usage and timings recorded. Base-rate cost estimate is separate from an actual billing receipt. No numeric confidence values were fabricated.
- Variance: one chronological trajectory. No stability estimate or real-world generalisation interval. Event-level correlations prevent treating 36 posts as independent trials.
- Unresolved task-design issues: non-exhaustive tags, overlapping evidence categories, fused status dimensions, implicit site geography, and undefined event granularity. See FINDINGS.md for concrete examples.
- Static report checks: one variant, 36 cases, populated agreement values and 36 existing trace links. Browser rendering through a temporary localhost server was attempted but unavailable; no visual rendering claim is made.
- Credentials: no API key was written to the output files or report. Key-prefix scan over outputs and work found no matching credential strings.
