# Live OpenAI Decisions replay

Start with [FINDINGS.md](FINDINGS.md) for the interpretation. [COMPARISON.md](COMPARISON.md) lists every incoming post and all report-flag disagreements. [report.html](report.html) contains the sortable 36-case agreement table with native trace links. The HTML is the bundled evaluation skill's lite report; it does not display an interactive event player.

Native requests/responses are in baseline/calls. Model-built event histories are in baseline/predictions.json. The original dataset is separate. The Python runner is provided beside this directory as run_decisions_replay.py. Re-running may incur API charges; use OPENAI_API_KEY in your environment or its hidden credential prompt. Never place the key in a command argument or commit it.

This is one exploratory baseline, not a validated clinical system or accepted benchmark.
