"""Optional PostgreSQL persistence, isolated from public and from raw files."""
import json
import os
import re
from .model import ROOT, TABLES, validate

SCHEMAS = {
    "sites": "site_id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT, arrondissement INTEGER, lat DOUBLE PRECISION, lon DOUBLE PRECISION, trauma_level INTEGER, beds INTEGER, avg_daily_rbc_units NUMERIC, home_bank_id TEXT, site_type TEXT NOT NULL, is_synthetic BOOLEAN NOT NULL, metadata_status TEXT",
    "units": "unit_id TEXT PRIMARY KEY, source_unit_id TEXT, blood_type TEXT NOT NULL, component TEXT NOT NULL, site_id TEXT NOT NULL REFERENCES sites(site_id), initial_site_id TEXT NOT NULL REFERENCES sites(site_id), collection_date DATE NOT NULL, expiry_date DATE NOT NULL, status TEXT NOT NULL CHECK(status IN ('available','used','expired')), used_date DATE, is_synthetic BOOLEAN NOT NULL",
    "transfers": "transfer_id TEXT PRIMARY KEY, unit_id TEXT NOT NULL REFERENCES units(unit_id), from_site_id TEXT NOT NULL REFERENCES sites(site_id), to_site_id TEXT NOT NULL REFERENCES sites(site_id), transfer_date DATE NOT NULL, reason TEXT, is_synthetic BOOLEAN NOT NULL",
    "daily_usage": "date DATE NOT NULL, site_id TEXT NOT NULL REFERENCES sites(site_id), blood_type TEXT NOT NULL, units_used INTEGER NOT NULL CHECK(units_used>=0), partial_day BOOLEAN NOT NULL, source TEXT NOT NULL, is_synthetic BOOLEAN NOT NULL, PRIMARY KEY(date,site_id,blood_type)",
    "planned_activity": "activity_id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES sites(site_id), date DATE NOT NULL, procedure TEXT NOT NULL, blood_type TEXT NOT NULL, units_expected INTEGER NOT NULL CHECK(units_expected>0), priority TEXT NOT NULL, is_synthetic BOOLEAN NOT NULL",
    "travel_times": "from_site_id TEXT NOT NULL REFERENCES sites(site_id), to_site_id TEXT NOT NULL REFERENCES sites(site_id), distance_km NUMERIC, minutes_normal INTEGER, minutes_rush INTEGER, route_status TEXT NOT NULL, is_synthetic BOOLEAN NOT NULL, PRIMARY KEY(from_site_id,to_site_id)"
}
CLOCK_DATE = "(c.as_of AT TIME ZONE 'Europe/Paris')::date"
VIEWS = """
CREATE VIEW blood_stock AS
SELECT u.*, u.expiry_date - CLOCK_DATE AS days_to_expiry,
       u.expiry_date - CLOCK_DATE <= 7 AS expiring_soon
FROM units u CROSS JOIN simulation_clock c
WHERE u.status='available' AND u.expiry_date > CLOCK_DATE;

CREATE VIEW stock_by_site AS
SELECT s.site_id, b.blood_type, COUNT(u.unit_id) AS units_available,
       COUNT(u.unit_id) FILTER (WHERE u.expiring_soon) AS units_expiring_7d
FROM sites s CROSS JOIN (VALUES ('O+'),('O-'),('A+'),('A-'),('B+'),('B-'),('AB+'),('AB-')) b(blood_type)
LEFT JOIN blood_stock u ON u.site_id=s.site_id AND u.blood_type=b.blood_type
WHERE s.site_type IN ('hospital','blood_bank') GROUP BY s.site_id,b.blood_type;

CREATE VIEW stock_by_type AS
WITH types(blood_type) AS (VALUES ('O+'),('O-'),('A+'),('A-'),('B+'),('B-'),('AB+'),('AB-')),
stock AS (SELECT blood_type, COUNT(*) AS qty FROM blood_stock GROUP BY blood_type),
usage AS (
 SELECT d.blood_type, SUM(d.units_used)::numeric / COUNT(DISTINCT d.date) AS per_day
 FROM daily_usage d CROSS JOIN simulation_clock c
 WHERE NOT d.partial_day AND d.date >= CLOCK_DATE-(c.state->'scenario'->>'baseline_window_days')::integer AND d.date < CLOCK_DATE
 GROUP BY d.blood_type
)
SELECT t.blood_type, COALESCE(s.qty,0) AS units_available, ROUND(u.per_day,2) AS avg_daily_usage,
 ROUND(COALESCE(s.qty,0)/NULLIF(u.per_day,0),2) AS days_of_supply,
 CASE WHEN COALESCE(s.qty,0)=0 THEN 'CRITICAL'
      WHEN u.per_day IS NULL OR u.per_day=0 THEN 'UNKNOWN'
      WHEN COALESCE(s.qty,0)/u.per_day < (c.state->'scenario'->>'critical_days_of_supply')::numeric THEN 'CRITICAL'
      WHEN COALESCE(s.qty,0)/u.per_day < (c.state->'scenario'->>'low_days_of_supply')::numeric THEN 'LOW' ELSE 'OK' END AS status
FROM types t CROSS JOIN simulation_clock c LEFT JOIN stock s USING(blood_type) LEFT JOIN usage u USING(blood_type);
""".replace("CLOCK_DATE", CLOCK_DATE)

def safe_schema(name):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) or name == "public" or name.startswith("pg_") or name == "information_schema":
        raise ValueError("Use a dedicated lowercase demo schema, not public or a system schema")
    return name

def connect():
    try:
        import psycopg
        from dotenv import load_dotenv
    except ImportError as e:
        raise SystemExit("Database mode needs: python -m pip install -r blood-storage/requirements.txt") from e
    load_dotenv(ROOT / "blood-storage" / ".env")
    uri = os.environ.get("AIVEN_PG_URI")
    if not uri:
        raise SystemExit("Set AIVEN_PG_URI in the environment or blood-storage/.env")
    return psycopg.connect(uri)

def copy_world(cur, world):
    for name in TABLES:
        rows = world[name]
        columns = list(rows[0])
        # Only column identifiers already present in the fixed schema are accepted.
        if any(not re.fullmatch(r"[a-z_]+", c) or not re.search(r"\b" + c + r"\s+(TEXT|DATE|INTEGER|NUMERIC|BOOLEAN|DOUBLE)\b", SCHEMAS[name]) for c in columns):
            raise ValueError("Unexpected canonical column in " + name)
        with cur.copy("COPY " + name + " (" + ",".join('"' + col + '"' for col in columns) + ") FROM STDIN") as copy:
            for r in rows:
                copy.write_row([None if r[c] == "" else r[c] for c in columns])
    state = {k: v for k, v in world.items() if k not in TABLES}
    cur.execute("INSERT INTO simulation_clock(singleton,as_of,state) VALUES(true,%s,%s::jsonb)", (world["clock"], json.dumps(state)))

def load_database(world, schema="blood_demo", reset=False):
    schema = safe_schema(schema)
    validate(world)
    with connect() as conn, conn.cursor() as cur:
        cur.execute('CREATE SCHEMA IF NOT EXISTS "' + schema + '"')
        cur.execute('SET LOCAL search_path TO "' + schema + '"')
        for name in (*TABLES, "simulation_clock"):
            cur.execute("SELECT to_regclass(%s)", (schema + "." + name,))
            if cur.fetchone()[0] is not None and not reset:
                raise ValueError(f"Demo tables exist in {schema}. Pass --reset to replace only this module's objects.")
        if reset:
            for name in ["stock_by_type", "stock_by_site", "blood_stock"]:
                cur.execute("DROP VIEW IF EXISTS " + name)
            for name in ["transfers", "daily_usage", "planned_activity", "travel_times", "units", "sites", "simulation_clock"]:
                cur.execute("DROP TABLE IF EXISTS " + name)
        for name in TABLES:
            cur.execute("CREATE TABLE " + name + " (" + SCHEMAS[name] + ")")
        cur.execute("CREATE TABLE simulation_clock(singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK(singleton), as_of TIMESTAMPTZ NOT NULL, state JSONB NOT NULL)")
        copy_world(cur, world)
        cur.execute(VIEWS)
    return {"schema": schema, "status": "loaded", "units": len(world["units"])}

def database_tick(schema, advance, seed=0):
    schema = safe_schema(schema)
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SET LOCAL search_path TO "' + schema + '"')
        cur.execute("SELECT state FROM simulation_clock WHERE singleton FOR UPDATE")
        row = cur.fetchone()
        if row is None:
            raise ValueError("Load the demo database first")
        world = row[0]
        for name in TABLES:
            ordering = " ORDER BY transfer_date, (transfer_id LIKE 'SIM-%'), transfer_id" if name == "transfers" else ""
            cur.execute("SELECT * FROM " + name + ordering)
            columns = [d.name for d in cur.description]
            world[name] = [{k: "" if v is None else str(v) for k, v in zip(columns, values)} for values in cur.fetchall()]
        validate(world)
        result = advance(world, seed=seed)
        validate(world)
        for name in ["transfers", "daily_usage", "planned_activity", "travel_times", "units", "sites", "simulation_clock"]:
            cur.execute("DELETE FROM " + name)
        copy_world(cur, world)
    return result
