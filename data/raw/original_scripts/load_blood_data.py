"""Load blood_storage.csv into the Aiven PostgreSQL database.

Creates:
  table  blood_units     one row per bag (the CSV)
  view   blood_stock     bags in stock now, with days_to_expiry / expiring_soon
  view   stock_by_site   bags in stock per site and blood type
  view   stock_by_type   days of supply per blood type + OK / LOW / CRITICAL

Run once (or again to reset the demo):  python load_blood_data.py
Needs AIVEN_PG_URI in the .env file.
"""
import csv
import os

import psycopg
from dotenv import load_dotenv

CSV_FILE = "blood_storage.csv"
COLUMNS = ["unit_id", "blood_type", "bank", "location",
           "collection_date", "expiry_date", "status", "used_date"]

SQL_SETUP = """
DROP VIEW IF EXISTS stock_by_type, stock_by_site, blood_stock;
DROP TABLE IF EXISTS blood_units;

CREATE TABLE blood_units (
    unit_id         TEXT PRIMARY KEY,   -- e.g. U-00123
    blood_type      TEXT NOT NULL,      -- O+, O-, A+, A-, B+, B-, AB+, AB-
    bank            TEXT NOT NULL,      -- EFS bank that collected it: Crozatier / Cabanel
    location        TEXT NOT NULL,      -- where the bag is now (or the hospital that used it)
    collection_date DATE NOT NULL,
    expiry_date     DATE NOT NULL,      -- perishable date = collection + 42 days
    status          TEXT NOT NULL,      -- available / used / expired
    used_date       DATE
);

-- bags in stock right now, with perishability computed live from today's date
CREATE VIEW blood_stock AS
SELECT unit_id, blood_type, bank, location, collection_date, expiry_date,
       expiry_date - CURRENT_DATE          AS days_to_expiry,
       (expiry_date - CURRENT_DATE) <= 7   AS expiring_soon
FROM blood_units
WHERE status = 'available';

-- how many bags each site holds, per blood type
CREATE VIEW stock_by_site AS
SELECT location AS site, blood_type,
       COUNT(*)                                  AS units_available,
       COUNT(*) FILTER (WHERE expiring_soon)     AS units_expiring_7d,
       MIN(days_to_expiry)                       AS soonest_expiry_days
FROM blood_stock
GROUP BY location, blood_type;

-- national picture per blood type: what triggers the agent
CREATE VIEW stock_by_type AS
WITH stock AS (
    SELECT blood_type, COUNT(*) AS units_available
    FROM blood_units WHERE status = 'available' GROUP BY blood_type
), usage AS (
    SELECT blood_type, COUNT(*) / 7.0 AS avg_daily_usage
    FROM blood_units
    WHERE status = 'used' AND used_date > CURRENT_DATE - 7
    GROUP BY blood_type
)
SELECT s.blood_type, s.units_available,
       ROUND(u.avg_daily_usage, 1)                          AS avg_daily_usage,
       ROUND(s.units_available / NULLIF(u.avg_daily_usage, 0), 1) AS days_of_supply,
       CASE WHEN s.units_available / NULLIF(u.avg_daily_usage, 0) < 3 THEN 'CRITICAL'
            WHEN s.units_available / NULLIF(u.avg_daily_usage, 0) < 6 THEN 'LOW'
            ELSE 'OK' END                                   AS status
FROM stock s LEFT JOIN usage u USING (blood_type)
ORDER BY days_of_supply NULLS LAST;
"""


def main():
    load_dotenv()
    uri = os.environ.get("AIVEN_PG_URI")
    if not uri:
        raise SystemExit("AIVEN_PG_URI is missing from the .env file")

    with psycopg.connect(uri) as conn, conn.cursor() as cur:
        cur.execute(SQL_SETUP)
        # copy only the columns the database stores (days_to_expiry is computed live)
        with open(CSV_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            with cur.copy(f"COPY blood_units ({', '.join(COLUMNS)}) FROM STDIN") as copy:
                for row in reader:
                    copy.write_row([row[c] or None for c in COLUMNS])
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM blood_units")
        print(f"Loaded {cur.fetchone()[0]} bags into blood_units\n")
        cur.execute("SELECT * FROM stock_by_type")
        print(f"{'type':<5} {'units':>6} {'use/day':>8} {'days':>6}  status")
        for t, units, use, days, status in cur.fetchall():
            print(f"{t:<5} {units:>6} {use or 0:>8} {days or '-':>6}  {status}")


if __name__ == "__main__":
    main()
