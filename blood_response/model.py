from collections import Counter, defaultdict
from copy import deepcopy
import csv
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "canonical"
TABLES = ("sites", "units", "transfers", "daily_usage", "planned_activity", "travel_times")

def load_world(folder=DEFAULT_DATA):
    folder = Path(folder)
    world = {}
    for name in TABLES:
        with (folder / (name + ".csv")).open(encoding="utf-8", newline="") as f:
            world[name] = list(csv.DictReader(f))
    world["scenario"] = json.loads((folder / "scenario.json").read_text(encoding="utf-8"))
    world["clock"] = world["scenario"]["simulation_start"]
    world["tick"] = 0
    world["next_unit_number"] = 1
    world["next_transfer_number"] = 1
    return world

def validate(world):
    """Independently check canonical relations, chronology and consumption totals."""
    groups = set(world["scenario"]["blood_types"])
    today = datetime.fromisoformat(world["clock"]).date()
    sites = {r["site_id"]: r for r in world["sites"]}
    units = {r["unit_id"]: r for r in world["units"]}
    if len(sites) != len(world["sites"]) or len(units) != len(world["units"]):
        raise ValueError("Duplicate site/unit ID")
    hospitals = {k for k, v in sites.items() if v["site_type"] == "hospital"}
    for s in sites.values():
        if s["site_type"] not in {"hospital", "blood_bank", "external"}:
            raise ValueError("Unknown site type")
        if s["site_id"] in hospitals and sites.get(s["home_bank_id"], {}).get("site_type") != "blood_bank":
            raise ValueError("Hospital home bank is missing or is not a blood bank")
    actual = Counter()
    for u in units.values():
        if u["site_id"] not in sites or u["initial_site_id"] not in sites or u["blood_type"] not in groups:
            raise ValueError("Unknown unit reference")
        if u["component"] != "RBC" or str(u["is_synthetic"]).lower() != "true":
            raise ValueError("Unsupported component or non-synthetic unit")
        collected, expires = date.fromisoformat(u["collection_date"]), date.fromisoformat(u["expiry_date"])
        if not collected <= today or expires <= collected:
            raise ValueError("Invalid unit dates")
        if u["status"] == "used":
            used = date.fromisoformat(u["used_date"])
            if not collected <= used < expires or used > today or u["site_id"] not in hospitals:
                raise ValueError("Invalid unit use")
            actual[(u["used_date"], u["site_id"], u["blood_type"])] += 1
        elif u["status"] not in {"available", "expired"} or u["used_date"]:
            raise ValueError("Invalid unit status/use date")
        if u["status"] == "available" and expires <= today:
            raise ValueError("Expired unit marked available")
    declared = {}
    for r in world["daily_usage"]:
        key = (r["date"], r["site_id"], r["blood_type"])
        if date.fromisoformat(r["date"]) > today:
            raise ValueError("Usage cannot be in the future")
        if key in declared or r["site_id"] not in hospitals or r["blood_type"] not in groups:
            raise ValueError("Invalid/duplicate usage key")
        if str(r["partial_day"]).lower() not in {"true", "false"} or int(r["units_used"]) < 0:
            raise ValueError("Invalid usage value")
        declared[key] = int(r["units_used"])
    if any(actual[k] != declared.get(k, 0) for k in set(actual) | set(declared)):
        raise ValueError("Consumption ledger does not match daily usage")
    previous, previous_date = {}, {}
    seen = set()
    for t in world["transfers"]:
        if t["transfer_id"] in seen or t["unit_id"] not in units or t["from_site_id"] not in sites or t["to_site_id"] not in sites:
            raise ValueError("Invalid transfer reference")
        seen.add(t["transfer_id"])
        u = units[t["unit_id"]]
        movement_date = date.fromisoformat(t["transfer_date"])
        if movement_date > today or t["from_site_id"] == t["to_site_id"]:
            raise ValueError("Transfer must be a completed movement between different sites")
        if t["unit_id"] in previous_date and movement_date < previous_date[t["unit_id"]]:
            raise ValueError("Movement history is not chronological")
        if not u["collection_date"] <= t["transfer_date"] < u["expiry_date"] or (u["used_date"] and t["transfer_date"] > u["used_date"]):
            raise ValueError("Invalid transfer date")
        if t["unit_id"] in previous and previous[t["unit_id"]] != t["from_site_id"]:
            raise ValueError("Broken movement history")
        if t["unit_id"] not in previous and u["initial_site_id"] != t["from_site_id"]:
            raise ValueError("Initial site disagrees with movement history")
        previous[t["unit_id"]] = t["to_site_id"]
        previous_date[t["unit_id"]] = movement_date
    if any(units[uid]["site_id"] != location for uid, location in previous.items()):
        raise ValueError("Movement history disagrees with current unit location")
    if any(u["site_id"] != u["initial_site_id"] for uid, u in units.items() if uid not in previous):
        raise ValueError("Unit location changed without a movement record")
    route_keys = set()
    for r in world["travel_times"]:
        key = (r["from_site_id"], r["to_site_id"])
        if key in route_keys or key[0] not in sites or key[1] not in sites or key[0] == key[1]:
            raise ValueError("Invalid/duplicate route")
        route_keys.add(key)
        if r["route_status"] == "provided_estimate":
            if float(r["distance_km"]) <= 0 or int(r["minutes_normal"]) <= 0 or int(r["minutes_rush"]) < int(r["minutes_normal"]):
                raise ValueError("Invalid travel estimate")
        elif r["route_status"] != "unavailable" or r["minutes_normal"] or r["minutes_rush"]:
            raise ValueError("Unknown route must have no invented ETA")
    activity_ids = set()
    for p in world["planned_activity"]:
        date.fromisoformat(p["date"])
        if p["activity_id"] in activity_ids or p["priority"] not in {"elective", "scheduled_critical"}:
            raise ValueError("Invalid/duplicate planned activity")
        activity_ids.add(p["activity_id"])
        if p["site_id"] not in hospitals or p["blood_type"] not in groups or int(p["units_expected"]) <= 0:
            raise ValueError("Invalid planned activity")
    return {"status": "PASS", "sites": len(sites), "units": len(units), "available_units": sum(u["status"] == "available" for u in units.values()), "used_units": sum(actual.values()), "transfers": len(seen), "usage_rows": len(declared)}

def baselines(world):
    """Full observed days only, including explicit reconciled zeros."""
    today = datetime.fromisoformat(world["clock"]).date()
    start = today - timedelta(days=int(world["scenario"]["baseline_window_days"]))
    observations = defaultdict(dict)
    for r in world["daily_usage"]:
        when = date.fromisoformat(r["date"])
        if start <= when < today and str(r["partial_day"]).lower() == "false":
            observations[(r["site_id"], r["blood_type"])][r["date"]] = int(r["units_used"])
    return {key: sum(values.values()) / len(values) for key, values in observations.items()}

def available_units(world, site, blood, on_date):
    return sorted((u for u in world["units"] if u["status"] == "available" and u["site_id"] == site and u["blood_type"] == blood and date.fromisoformat(u["expiry_date"]) > on_date), key=lambda u: (u["expiry_date"], u["unit_id"]))

def classify_stock(units, daily, scenario):
    if units == 0:
        return "CRITICAL"
    if daily is None or daily <= 0:
        return "UNKNOWN"
    if units / daily < scenario["critical_days_of_supply"]:
        return "CRITICAL"
    if units / daily < scenario["low_days_of_supply"]:
        return "LOW"
    return "OK"

def plan(world, traffic="rush"):
    """Next complete-day estimate and non-executing, shared-bank allocations."""
    now = datetime.fromisoformat(world["clock"])
    day = now.date() + timedelta(days=1)
    scenario = world["scenario"]
    if not scenario["known_planning_start"] <= day.isoformat() <= scenario["known_planning_end"]:
        raise ValueError("Next day is outside supplied planning coverage; no zero-demand extrapolation is allowed")
    baseline = baselines(world)
    sites = {s["site_id"]: s for s in world["sites"]}
    hospitals = {k: v for k, v in sites.items() if v["site_type"] == "hospital"}
    planned = Counter()
    critical = Counter()
    for r in world["planned_activity"]:
        if r["date"] == day.isoformat():
            planned[(r["site_id"], r["blood_type"])] += int(r["units_expected"])
            if r["priority"] == "scheduled_critical":
                critical[(r["site_id"], r["blood_type"])] += int(r["units_expected"])
    routes = {(r["from_site_id"], r["to_site_id"]): r for r in world["travel_times"]}
    bank_pools, reserves = {}, {}
    for bank, info in sites.items():
        if info["site_type"] != "blood_bank":
            continue
        for blood in scenario["blood_types"]:
            key = (bank, blood)
            total = sum(baseline.get((h, blood), 0) for h, s in hospitals.items() if s["home_bank_id"] == bank)
            reserves[key] = math.ceil(total * scenario["transfer_safety_reserve_days"])
            stock = available_units(world, bank, blood, day)
            # Allocate FEFO from the releasable part; the shared pool is decremented.
            bank_pools[key] = stock[:max(0, len(stock) - reserves[key])]
    rows = []
    for h, s in sorted(hospitals.items()):
        for blood in scenario["blood_types"]:
            key = (h, blood)
            mean = baseline.get(key)
            demand = math.ceil(max(mean, planned[key])) if mean is not None else None
            local = len(available_units(world, h, blood, day))
            rows.append({"site_id": h, "blood_type": blood, "baseline_daily_units": round(mean, 4) if mean is not None else None,
                "planned_units": planned[key], "scheduled_critical_units": critical[key], "forecast_units": demand,
                "local_usable_units": local, "stock_status": classify_stock(local, mean, scenario),
                "home_bank_id": s["home_bank_id"], "suggested_inbound_units": 0,
                "uncovered_units": max(0, demand - local) if demand is not None else None})
    suggestions = []
    ordered = sorted(rows, key=lambda r: (-int(r["scheduled_critical_units"] > 0), -int(r["uncovered_units"] or 0), r["site_id"], r["blood_type"]))
    for r in ordered:
        if not r["uncovered_units"]:
            continue
        route = routes.get((r["home_bank_id"], r["site_id"]))
        if not route or route["route_status"] != "provided_estimate":
            r["transfer_blocker"] = "unknown_route_eta"
            continue
        minutes = int(route["minutes_" + traffic])
        if minutes > 24 * 60:
            r["transfer_blocker"] = "cannot_arrive_within_planning_day"
            continue
        pool = bank_pools[(r["home_bank_id"], r["blood_type"])]
        chosen = pool[:r["uncovered_units"]]
        del pool[:len(chosen)]
        if chosen:
            r["suggested_inbound_units"] = len(chosen)
            r["uncovered_units"] -= len(chosen)
            suggestions.append({"from_site_id": r["home_bank_id"], "to_site_id": r["site_id"], "blood_type": r["blood_type"],
                "units": len(chosen), "unit_ids": [u["unit_id"] for u in chosen], "estimated_minutes": minutes,
                "traffic_assumption": traffic, "status": "proposal_requires_review"})
    return {"as_of": world["clock"], "planning_date": day.isoformat(), "is_synthetic": True,
        "demand_assumption": scenario["demand_rule"], "rows": rows, "transfer_proposals": suggestions,
        "bank_reserve_days": scenario["transfer_safety_reserve_days"],
        "uncovered_units": sum(r["uncovered_units"] or 0 for r in rows),
        "unknown_demand_rows": sum(r["forecast_units"] is None for r in rows),
        "notes": ["Proposals do not move inventory or execute database writes.", "No forecast future donations or external shipments are promised.",
            "Exact blood-group matching only; no compatibility or clinical allocation policy is modelled.",
            "Historical transfers have dates, not departure/arrival timestamps; proposed ETAs use unverified fixture estimates.",
            "Social information requests assessment; it is not automatically converted into blood units."]}

def poisson(rng, rate):
    if rate <= 0:
        return 0
    # Exact independent Poisson chunks avoid underflow when users increase tick length.
    if rate > 20:
        chunks = math.ceil(rate / 20)
        return sum(poisson(rng, rate / chunks) for _ in range(chunks))
    limit, product, count = math.exp(-rate), 1.0, 0
    while True:
        product *= rng.random()
        if product <= limit:
            return count
        count += 1

def advance(world, hours=1, seed=0):
    if hours != 1:
        raise ValueError("This demo uses one-hour ticks; use multiple ticks to advance further")
    zone = ZoneInfo(world["scenario"]["timezone"])
    start = datetime.fromisoformat(world["clock"]).astimezone(zone)
    end = (start.astimezone(timezone.utc) + timedelta(hours=hours)).astimezone(zone)
    if end.date() > start.date() + timedelta(days=1):
        raise ValueError("Use ticks of at most one simulated day")
    # Baseline is calculated before the partial day is altered.
    means = baselines(world)
    rng = random.Random(seed + int(world["tick"]))
    today = start.date()
    expired = used = donated = requested = 0
    before = sum(u["status"] == "available" for u in world["units"])
    for u in world["units"]:
        if u["status"] == "available" and date.fromisoformat(u["expiry_date"]) <= today:
            u["status"] = "expired"
            expired += 1
    hospitals = [s for s in world["sites"] if s["site_type"] == "hospital"]
    routes = {(r["from_site_id"], r["to_site_id"]): r for r in world["travel_times"]}
    observed = Counter()
    donation_rates = Counter()
    planned = Counter()
    for p in world["planned_activity"]:
        if p["date"] == today.isoformat():
            planned[(p["site_id"], p["blood_type"])] += int(p["units_expected"])
    if not world["scenario"]["snapshot_date"] <= today.isoformat() <= world["scenario"]["known_planning_end"]:
        raise ValueError("Simulation is outside the declared fixture horizon")
    for h in hospitals:
        for blood in world["scenario"]["blood_types"]:
            mean = means.get((h["site_id"], blood))
            if mean is None:
                raise ValueError("Cannot simulate demand without a complete-day baseline")
            rate = max(mean, planned[(h["site_id"], blood)]) * hours / 24
            demand = poisson(rng, rate)
            requested += demand
            local = available_units(world, h["site_id"], blood, today)
            route = routes.get((h["home_bank_id"], h["site_id"]))
            bank = []
            if route and route["route_status"] == "provided_estimate" and int(route["minutes_rush"]) <= hours * 60:
                bank = available_units(world, h["home_bank_id"], blood, today)
            for u in (local + bank)[:demand]:
                if u["site_id"] != h["site_id"]:
                    world["transfers"].append({"transfer_id": f"SIM-TR-{world['next_transfer_number']:08d}", "unit_id": u["unit_id"],
                        "from_site_id": u["site_id"], "to_site_id": h["site_id"], "transfer_date": today.isoformat(),
                        "reason": "simulated_replenishment", "is_synthetic": "true"})
                    world["next_transfer_number"] += 1
                u.update(status="used", used_date=today.isoformat(), site_id=h["site_id"])
                used += 1
                observed[(h["site_id"], blood)] += 1
            donation_rates[(h["home_bank_id"], blood)] += rate * world["scenario"]["donation_to_usage_ratio"][blood]
    for (bank, blood), rate in sorted(donation_rates.items()):
        for _ in range(poisson(rng, rate)):
            uid = f"SIM-UNIT-{world['next_unit_number']:08d}"
            world["next_unit_number"] += 1
            world["units"].append({"unit_id": uid, "source_unit_id": "", "blood_type": blood, "component": "RBC", "site_id": bank,
                "initial_site_id": bank, "collection_date": today.isoformat(),
                "expiry_date": (today + timedelta(days=world["scenario"]["simulation_shelf_life_days"])).isoformat(),
                "status": "available", "used_date": "", "is_synthetic": "true"})
            donated += 1
    if end.date() > start.date():
        for r in world["daily_usage"]:
            if r["date"] == start.date().isoformat():
                r["partial_day"] = "false"
    index = {(r["date"], r["site_id"], r["blood_type"]): r for r in world["daily_usage"]}
    for h in hospitals:
        for blood in world["scenario"]["blood_types"]:
            key = (today.isoformat(), h["site_id"], blood)
            r = index.get(key)
            if r is None:
                r = {"date": key[0], "site_id": key[1], "blood_type": blood, "units_used": 0,
                    "partial_day": "true", "source": "simulated", "is_synthetic": "true"}
                world["daily_usage"].append(r)
            r["units_used"] = str(int(r["units_used"]) + observed[(h["site_id"], blood)])
    # Consumption belongs to [start, end). Apply the next expiry boundary
    # after recording the preceding day's usage.
    for u in world["units"]:
        if u["status"] == "available" and date.fromisoformat(u["expiry_date"]) <= end.date():
            u["status"] = "expired"
            expired += 1
    world["clock"] = end.isoformat()
    world["tick"] += 1
    after = sum(u["status"] == "available" for u in world["units"])
    if after != before - used - expired + donated:
        raise AssertionError("Inventory conservation failed")
    return {"tick": world["tick"], "as_of": world["clock"], "requested": requested, "used": used,
        "unmet_requests": requested - used, "donated": donated, "expired": expired, "available": after,
        "inventory_conservation": "PASS"}
