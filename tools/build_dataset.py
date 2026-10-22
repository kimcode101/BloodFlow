"""Deterministically align the supplied fixtures. No network or database access."""
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "canonical"
TYPES = ("O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-")
SNAPSHOT = date(2026, 10, 22)
UNIT_FIELDS = ["unit_id", "source_unit_id", "blood_type", "component", "site_id", "initial_site_id", "collection_date", "expiry_date", "status", "used_date", "is_synthetic"]

def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def save(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

def js(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")

def check(condition, message):
    if not condition:
        raise ValueError(message)

def unique(rows, key):
    values = [r[key] for r in rows]
    check(len(values) == len(set(values)), f"Duplicate {key}")

def build():
    source = {name: read(RAW / "team_bundle" / (name + ".csv")) for name in ["sites", "units", "transfers", "daily_usage", "planned_activity", "travel_times"]}
    for name, key in [("sites", "site_id"), ("units", "unit_id"), ("transfers", "transfer_id"), ("planned_activity", "activity_id")]:
        unique(source[name], key)
    sites = []
    for row in source["sites"]:
        r = dict(row)
        r["site_type"] = r.pop("type")
        r["is_synthetic"] = "true"
        r["metadata_status"] = "provided_demo_fixture_unverified"
        sites.append(r)
    site_ids = {r["site_id"] for r in sites}
    hospitals = {r["site_id"]: r for r in sites if r["site_type"] == "hospital"}
    for r in hospitals.values():
        check(r["home_bank_id"] in site_ids, "Unknown home bank")
    site_types = {r["site_id"]: r["site_type"] for r in sites}
    for r in hospitals.values():
        check(site_types[r["home_bank_id"]] == "blood_bank", "Home site is not a bank")

    id_map = {r["unit_id"]: "UNIT-" + r["unit_id"].zfill(8) for r in source["units"]}
    chains = defaultdict(list)
    transfers = []
    for r in sorted(source["transfers"], key=lambda x: (x["transfer_date"], int(x["transfer_id"]))):
        check(r["unit_id"] in id_map, "Transfer has an unknown unit")
        check(r["from_site_id"] in site_ids and r["to_site_id"] in site_ids, "Transfer has an unknown site")
        check(r["from_site_id"] != r["to_site_id"], "Self-transfer")
        chains[r["unit_id"]].append(r)
        transfers.append({"transfer_id": "TR-" + r["transfer_id"].zfill(7), "unit_id": id_map[r["unit_id"]],
            "from_site_id": r["from_site_id"], "to_site_id": r["to_site_id"],
            "transfer_date": r["transfer_date"], "reason": r["reason"].replace(" ", "_").replace("-", "_"), "is_synthetic": "true"})
    units = []
    usage = Counter()
    for r in sorted(source["units"], key=lambda x: int(x["unit_id"])):
        check(r["blood_type"] in TYPES, "Unknown blood group")
        check(r["storage_site"] in site_ids, "Unit has an unknown site")
        check(r["status"] in {"used", "available", "expired"}, "Unknown unit status")
        collected, expires = date.fromisoformat(r["collection_date"]), date.fromisoformat(r["expiry_date"])
        check(collected <= SNAPSHOT and expires > collected, "Invalid collection/expiry date")
        check((r["is_synthetic"].lower() == "true"), "Mixed real/synthetic units are not supported")
        if r["status"] == "used":
            used = date.fromisoformat(r["used_date"])
            check(collected <= used < expires and used <= SNAPSHOT, "Invalid use date")
            check(r["storage_site"] in hospitals, "Used unit is not at a hospital")
            usage[(r["used_date"], r["storage_site"], r["blood_type"])] += 1
        else:
            check(not r["used_date"], "Unused unit has a use date")
        if r["status"] == "available":
            check(expires > SNAPSHOT, "Available unit is expired at snapshot")
        history = chains[r["unit_id"]]
        for i, movement in enumerate(history):
            check(r["collection_date"] <= movement["transfer_date"] < r["expiry_date"], "Transfer outside unit life")
            check(not r["used_date"] or movement["transfer_date"] <= r["used_date"], "Transfer after use")
            if i:
                check(history[i-1]["to_site_id"] == movement["from_site_id"], "Broken transfer chain")
        check(not history or history[-1]["to_site_id"] == r["storage_site"], "Transfer history disagrees with unit location")
        units.append({"unit_id": id_map[r["unit_id"]], "source_unit_id": r["unit_id"], "blood_type": r["blood_type"],
            "component": "RBC", "site_id": r["storage_site"],
            "initial_site_id": history[0]["from_site_id"] if history else r["storage_site"],
            "collection_date": r["collection_date"], "expiry_date": r["expiry_date"],
            "status": r["status"], "used_date": r["used_date"], "is_synthetic": "true"})

    supplied_usage = {}
    partial = {}
    for r in source["daily_usage"]:
        key = (r["date"], r["site_id"], r["blood_type"])
        check(key not in supplied_usage, "Duplicate daily usage key")
        check(r["site_id"] in hospitals and r["blood_type"] in TYPES, "Invalid usage reference")
        check(int(r["units_used"]) >= 0, "Negative usage")
        check(r["partial_day"].lower() in {"true", "false"}, "Invalid partial-day boolean")
        supplied_usage[key] = int(r["units_used"])
        flag = r["partial_day"].lower()
        check(r["date"] not in partial or partial[r["date"]] == flag, "Inconsistent day completeness")
        partial[r["date"]] = flag
    check(all(supplied_usage.get(k, 0) == usage[k] for k in set(supplied_usage) | set(usage)), "Daily usage does not reconcile with the unit ledger")
    dates = sorted(partial)
    check(dates[-1] == SNAPSHOT.isoformat(), "Usage horizon disagrees with snapshot")
    check(dates == [(date.fromisoformat(dates[0]) + timedelta(days=i)).isoformat() for i in range(len(dates))], "Missing usage day")
    daily = []
    for day in dates:
        for site in sorted(hospitals):
            for blood in TYPES:
                key = (day, site, blood)
                daily.append({"date": day, "site_id": site, "blood_type": blood,
                    "units_used": supplied_usage.get(key, 0), "partial_day": partial[day],
                    "source": "provided" if key in supplied_usage else "derived_zero_from_reconciled_unit_ledger", "is_synthetic": "true"})
    plans = []
    for r in sorted(source["planned_activity"], key=lambda x: int(x["activity_id"])):
        check(r["site_id"] in hospitals and r["blood_type"] in TYPES, "Invalid planned activity reference")
        check(date.fromisoformat(r["date"]) > SNAPSHOT and int(r["units_expected"]) > 0, "Invalid planned date/quantity")
        check(r["priority"] in {"elective", "scheduled-critical"}, "Unknown activity priority")
        plans.append(dict(r, activity_id="ACT-" + r["activity_id"].zfill(7), priority=r["priority"].replace("-", "_"), is_synthetic="true"))
    given_routes = {}
    for r in source["travel_times"]:
        key = (r["from_site_id"], r["to_site_id"])
        check(key not in given_routes and key[0] in site_ids and key[1] in site_ids and key[0] != key[1], "Invalid/duplicate travel route")
        check(float(r["distance_km"]) > 0 and int(r["minutes_normal"]) > 0 and int(r["minutes_rush"]) >= int(r["minutes_normal"]), "Invalid travel duration")
        given_routes[key] = r
    routes = []
    for a in sorted(site_ids):
        for b in sorted(site_ids):
            if a == b:
                continue
            r = given_routes.get((a, b))
            routes.append({"from_site_id": a, "to_site_id": b, "distance_km": r["distance_km"] if r else "",
                "minutes_normal": r["minutes_normal"] if r else "", "minutes_rush": r["minutes_rush"] if r else "",
                "route_status": "provided_estimate" if r else "unavailable", "is_synthetic": "true"})
    for t in transfers:
        key = (t["from_site_id"], t["to_site_id"])
        check(key in given_routes or site_types[key[0]] == "external" or site_types[key[1]] == "external", "Missing internal transfer route")

    # Two stock files describe different synthetic worlds. Normalize the older
    # one separately, with separate IDs; never add it to the active ledger.
    aliases = {"Lariboisière": "H1", "Pitié-Salpêtrière": "H2", "HEGP": "H3", "Bichat": "H4", "Crozatier": "B1", "Cabanel": "B2"}
    legacy = read(RAW / "legacy_stock" / "blood_storage.csv")
    alternate = []
    for r in legacy:
        check(r["location"] in aliases and r["bank"] in aliases, "Unmapped legacy site")
        alternate.append({"unit_id": "LEGACY-" + r["unit_id"], "source_unit_id": r["unit_id"], "blood_type": r["blood_type"],
            "component": "RBC", "site_id": aliases[r["location"]], "initial_site_id": aliases[r["bank"]],
            "collection_date": r["collection_date"], "expiry_date": r["expiry_date"], "status": r["status"],
            "used_date": r["used_date"], "is_synthetic": "true"})
    legacy_by_numeric = {str(int(r["unit_id"][2:])): r for r in legacy}
    overlap = set(id_map) & set(legacy_by_numeric)
    conflicting_ids = sorted(k for k in overlap if any(next(r for r in source["units"] if r["unit_id"] == k)[f] != legacy_by_numeric[k][f] for f in ["blood_type", "collection_date", "expiry_date"]))

    config = {
        "schema_version": "1.0", "dataset_id": "paris_blood_demo_20261022", "is_synthetic": True,
        "snapshot_date": SNAPSHOT.isoformat(), "timezone": "Europe/Paris",
        "simulation_start": "2026-10-22T12:00:00+02:00",
        "simulation_start_note": "No exact snapshot time was supplied. Noon is an explicit demo assumption, consistent with partial-day usage; it is not an observed time.",
        "component": "RBC", "blood_types": list(TYPES), "expiry_rule": "expiry_date <= simulated date is unavailable",
        "baseline_window_days": 7, "partial_days_in_baseline": False,
        "demand_rule": "max(historical_full_day_mean, planned_units_for_that_day)",
        "demand_rule_note": "A planning floor prevents adding a full baseline to scheduled demand that it may already contain. This is an explicit provisional demo assumption, not a validated forecast.",
        "known_planning_start": min(r["date"] for r in plans), "known_planning_end": max(r["date"] for r in plans),
        "low_days_of_supply": 6, "critical_days_of_supply": 3,
        "donation_to_usage_ratio": {t: (0.6 if t == "O-" else 1.0) for t in TYPES},
        "simulation_shelf_life_days": 42, "transfer_safety_reserve_days": 1,
        "social_template_shift_days": 7, "social_window": ["2026-10-23", "2026-10-25"],
        "social_effect_on_demand": "qualitative_review_only; no unvalidated conversion from posts to transfusion units",
        "site_metadata_status": "all supplied clinical capacities and routing metadata are unverified demo assumptions"
    }
    for name, rows in [("sites", sites), ("units", units), ("transfers", transfers), ("daily_usage", daily), ("planned_activity", plans), ("travel_times", routes)]:
        save(OUT / (name + ".csv"), rows, UNIT_FIELDS if name == "units" else None)
    save(ROOT / "data" / "alternatives" / "legacy_units.csv", alternate, UNIT_FIELDS)
    save(OUT / "site_aliases.csv", [{"alias": a, "site_id": s} for a, s in aliases.items()])
    js(OUT / "scenario.json", config)

    social = ROOT / "paris-protest-social-simulation-v1"
    posts = [json.loads(s) for s in (social / "social_reports.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    shifted = []
    for r in posts:
        p = dict(r)
        p["scenario_id"] = config["dataset_id"]
        p["template_published_at"] = r["published_at"]
        p["template_available_at"] = r["available_at"]
        for key in ["published_at", "available_at"]:
            p[key] = (datetime.fromisoformat(r[key]).astimezone(ZoneInfo("Europe/Paris")) + timedelta(days=7)).isoformat()
        p["scenario_note"] = "Invented forward demo: shifted seven days from the original synthetic template; not a claim about real protests on these dates."
        p["reported_entity_context"] = []
        for entity in ["Hôpital-Démo-01", "Démo-Nord"]:
            if entity in p["text"]:
                p["reported_entity_context"].append({"entity": entity, "zone": "paris_northeast", "site_id": None,
                    "basis": "explicit_synthetic_scenario_location_binding_not_a_real_institution_identity"})
        shifted.append(p)
    jsonl(OUT / "social_reports.jsonl", shifted)
    expected = [json.loads(s) for s in (social / "expected_decisions.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    for r in expected:
        r["label_origin"] = "assistant_authored_template_reference_not_independently_reviewed"
        r["scenario_id"] = config["dataset_id"]
    jsonl(OUT / "expected_decisions.jsonl", expected)
    rubric = json.loads((social / "decision_rubric.json").read_text(encoding="utf-8"))
    rubric["model_input_policy"].append("template_published_at and template_available_at are provenance only. Evaluate timing against current_report.available_at in the forward scenario, not against the template dates.")
    rubric["model_input_policy"].append("reported_entity_context explicitly locates a fictional mentioned institution for this scenario; it is not a real hospital identity or verified medical claim.")
    js(OUT / "decision_rubric.json", rubric)
    js(OUT / "social_site_context.json", {
        "purpose": "Candidate facilities for review only, never inferred patient destinations or stock movements.",
        "demo_zone_candidates": {"paris_northeast": ["H1", "H4"], "paris_centre_east": ["H1", "H2"], "paris_west": ["H3", "B2"], "paris_south": ["H2", "H3"], "paris_unspecified": ["H1", "H2", "H3", "H4"]},
        "mapping_status": "coarse declared demo assumption; not validated catchment geography",
        "fictional_entities": {"Hôpital-Démo-01": {"zone": "paris_northeast", "site_id": None}, "Centre de collecte Démo-Nord": {"zone": "paris_northeast", "site_id": None}},
        "rule": "Fictional institutions are not silently equated to a real-named site. Unknown locations remain unknown without explicit entity evidence."
    })
    source_paths = sorted(p for p in RAW.rglob("*") if p.is_file())
    source_manifest = [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in source_paths]
    report = {
        "status": "PASS", "schema_version": "1.0", "snapshot_date": SNAPSHOT.isoformat(),
        "counts": {"sites": len(sites), "units": len(units), "available_units": sum(r["status"] == "available" for r in units),
            "used_units": sum(r["status"] == "used" for r in units), "transfers": len(transfers), "daily_usage": len(daily),
            "daily_usage_explicit_zero_rows_added": len(daily) - len(source["daily_usage"]), "planned_activities": len(plans),
            "travel_pairs": len(routes), "routes_without_eta": sum(r["route_status"] == "unavailable" for r in routes), "social_posts": len(shifted)},
        "reconciliation": {"daily_usage_equals_used_units": True, "transfer_chains_consistent": True, "source_unit_id_collisions_with_legacy": conflicting_ids,
            "legacy_available_units_excluded_from_active_stock": sum(r["status"] == "available" for r in legacy)},
        "explicit_limits": ["External site X1 has no travel-time estimate; unavailable routes cannot be scheduled.",
            "Partial-day 22 October usage is excluded from the baseline.", "Historical coverage is only the supplied window; no missing earlier days are invented.",
            "The original social fixture and recorded OpenAI baseline remain unchanged. No API call was made for the new forward scenario.",
            "No patient-level case dataset, live inventory feed, or validated social-to-demand conversion was supplied.",
            "Source clinical metadata, demand thresholds, shelf life and travel times are demo assumptions, not operational facts."],
        "sources": source_manifest
    }
    js(ROOT / "data" / "integration_report.json", report)
    print(json.dumps({"status": report["status"], "counts": report["counts"]}, indent=2))
    return report

if __name__ == "__main__":
    build()
