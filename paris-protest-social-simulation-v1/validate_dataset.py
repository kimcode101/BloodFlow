"""Validate the authored fixture offline. Does not call any API."""
from pathlib import Path
from datetime import datetime
from collections import Counter
import json

root = Path(__file__).resolve().parent
def read(name):
    return [json.loads(s) for s in (root/name).read_text(encoding="utf-8").splitlines() if s.strip()]
reports = read("social_reports.jsonl")
targets = read("expected_decisions.jsonl")
updates = read("expected_event_updates.jsonl")
rubric = json.loads((root/"decision_rubric.json").read_text(encoding="utf-8"))
catalog = json.loads((root/"scenario_catalog.json").read_text(encoding="utf-8"))
questions = {q["name"]: q for q in rubric["questions"]}
by_id = {r["report_id"]:r for r in reports}
assert len(reports) == len(targets) == len(by_id) == 36
assert Counter(r["published_at"][:10] for r in reports) == {"2026-10-16":12,"2026-10-17":12,"2026-10-18":12}
assert [r["available_at"] for r in reports] == sorted(r["available_at"] for r in reports)
assert set(by_id) == {t["report_id"] for t in targets}
assert len({t["report_id"] for t in targets}) == len(targets)
known_events = {e["event_id"] for e in catalog["events"]}
all_source_ids = {s["source_id"] for s in json.loads((root/"research_sources.json").read_text(encoding="utf-8"))}
seen, event_seen, previous = set(), set(), {}
for r,t in zip(reports,targets):
    rid = r["report_id"]
    assert rid == t["report_id"]
    assert r["is_synthetic"] and r["account_id"].startswith("SIM-")
    assert datetime.fromisoformat(r["published_at"]) < datetime.fromisoformat(r["available_at"])
    assert r["published_at"].endswith("+02:00")
    assert set(t["decisions"]) == set(questions)
    for key, val in t["decisions"].items():
        q=questions[key]
        if q["kind"] == "choice":
            assert val in q["options"], (rid,key,val)
        else:
            assert type(val) is int and 0 <= val <= 3
    assert t["paris_action"] in {"IGNORE","MONITOR","REVIEW","URGENT_REVIEW"}
    assert set(t["research_anchor_ids"]) <= all_source_ids
    assert "expected_event_id" not in r and "decisions" not in r
    assert set(t["comparison"]["related_prior_report_ids"]) <= seen
    for prior in t["comparison"]["related_prior_report_ids"]:
        assert by_id[prior]["available_at"] < r["available_at"]
    quote=r["quoted_report_id"]
    if quote:
        assert quote in seen
    event=t["comparison"]["expected_event_id"]
    contribution=t["comparison"]["contribution"]
    assert contribution in rubric["comparison_stage"]["contribution_options"]
    if event:
        assert event in known_events
        if contribution == "new_event":
            assert event not in event_seen
        else:
            assert event in event_seen
        event_seen.add(event)
    else:
        assert contribution == "unrelated"
    if contribution == "duplicate":
        assert quote is not None
        assert r["text"] == by_id[quote]["text"]
        assert t["paris_action"] == "IGNORE"
        assert t["expected_event_action_after"] == previous[event]["expected_event_action_after"]
    if event:
        previous[event]=t
    seen.add(rid)
assert event_seen == known_events
for u in updates:
    assert u["event_id"] in known_events
    assert u["latest_report_id"] == u["linked_report_ids"][-1]
    assert u["as_of"] == by_id[u["latest_report_id"]]["available_at"]
    for rid in u["linked_report_ids"]:
        assert by_id[rid]["available_at"] <= u["as_of"]
    assert by_id[u["last_substantive_report_id"]]["available_at"] == u["last_substantive_report_available_at"]
assert len(updates) == sum(t["comparison"]["expected_event_id"] is not None for t in targets)
print(json.dumps({"validation":"PASS","reports":len(reports),"reference_decisions":len(targets),"event_families":len(known_events),"event_updates":len(updates),"days":dict(Counter(r["published_at"][:10] for r in reports)),"paris_actions":dict(Counter(t["paris_action"] for t in targets)),"model_api_called":False},indent=2))
