"""Deterministic social handoff policy; no API calls or medical inference."""
PRIORITY = {"IGNORE": 0, "MONITOR": 1, "REVIEW": 2, "URGENT_REVIEW": 3}

def action(a, contribution):
    zone, timing = a.get("zone", "unknown"), a.get("timing", "unknown")
    level = a.get("reported_impact_level_mode")
    if zone in {"lyon", "nantes", "france_unspecified"} or contribution in {"duplicate", "historical_reference", "unrelated"}:
        return "IGNORE"
    if contribution in {"contradicts", "resolves"} or a.get("update_type") in {"correction_or_denial", "resolution"}:
        return "REVIEW"
    if timing == "past" or (a.get("impact_pathway") == "none" and level == 0):
        return "IGNORE"
    if zone == "unknown" or timing == "unknown" or level is None or a.get("impact_pathway") == "unclear":
        return "REVIEW"
    return "URGENT_REVIEW" if level == 3 else "REVIEW" if level == 2 else "MONITOR"

def normalize(reports, predictions):
    by_id = {r["report_id"]: r for r in reports}
    previous, report_events, events, result = {}, {}, {}, []
    for p in predictions:
        rid = p["report_id"]
        report = by_id[rid]
        if p["available_at"] != report["available_at"]:
            raise ValueError("Prediction/report clock mismatch; historical responses are not a forward-scenario API run")
        if previous and report["available_at"] < max(r["available_at"] for r in previous.values()):
            raise ValueError("Predictions are not chronological")
        a = p["assessment"]
        contribution, event_id = p["decisions"]["contribution"], p.get("event_id")
        quote = report.get("quoted_report_id")
        if quote in previous and report["text"] == previous[quote]["text"]:
            contribution, event_id = "duplicate", report_events[quote]
        event = dict(events.get(event_id, {})) if event_id else {}
        old = event.get("review_priority", "IGNORE")
        if contribution not in {"duplicate", "historical_reference"}:
            own = dict(a)
            if own.get("zone") in {"lyon", "nantes"}:
                own["zone"] = "paris_unspecified"
            event["review_priority"] = max([old, action(own, contribution)], key=PRIORITY.get)
            if contribution == "resolves":
                event.update(review_priority="REVIEW", event_phase="resolution_reported")
            else:
                event["event_phase"] = {"upcoming": "planned", "ongoing": "ongoing"}.get(a.get("timing"), event.get("event_phase", "unknown"))
            if contribution == "contradicts":
                event["evidence_status"] = "disputed"
            else:
                event.setdefault("evidence_status", "partially_supported" if contribution == "corroborates" else "unverified")
        if event_id:
            event.setdefault("review_priority", old)
            event.setdefault("event_phase", "unknown")
            event.setdefault("evidence_status", "unverified")
            events[event_id] = event
        result.append({"report_id": rid, "available_at": report["available_at"], "event_id": event_id,
            "paris_action": action(a, contribution), "event_phase": event.get("event_phase"),
            "evidence_status": event.get("evidence_status"), "event_review_priority": event.get("review_priority"),
            "zone": a.get("zone", "unknown"), "contribution": contribution, "blood_demand_increment": None,
            "origin": "deterministic_postprocessing_of_recorded_assessments_not_a_new_model_run"})
        previous[rid], report_events[rid] = report, event_id
    return result
