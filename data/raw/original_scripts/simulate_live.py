"""Make the blood stock 'live' for the demo.

Every few seconds (one tick = one simulated hour):
  - the 4 hospitals use bags (from their own stock first, else from their EFS bank)
  - donations arrive at Crozatier and Cabanel (O- donations are short -> O- keeps falling)
  - bags past their expiry date become 'expired'
Then it prints the stock per blood type.

Run:  python simulate_live.py        (stop with Ctrl+C)
Needs AIVEN_PG_URI in the .env file and load_blood_data.py run first.
"""
import math
import os
import random
import time

import psycopg
from dotenv import load_dotenv

TICK_SECONDS = 10      # real seconds between updates
HOURS_PER_TICK = 1     # simulated hours per update (raise it to speed up the demo)

# hospital -> (bags used per day, EFS bank that supplies it) -- same as the dataset
HOSPITALS = {
    "Pitié-Salpêtrière": (20, "Crozatier"),
    "Lariboisière":      (14, "Crozatier"),
    "HEGP":              (16, "Cabanel"),
    "Bichat":            (14, "Cabanel"),
}
DEMAND = {"O+": .36, "A+": .36, "B+": .08, "AB+": .03,
          "O-": .08, "A-": .06, "B-": .02, "AB-": .01}
SUPPLY = {t: 1.0 for t in DEMAND}   # donations / usage ratio per blood type
SUPPLY["O-"] = 0.6                  # O- donations can't keep up -> crisis continues


def poisson(lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= random.random()
        if p <= L:
            return k
        k += 1


def use_bags(cur, hospital, bank, blood_type, n):
    """Hospital uses n bags: its own stock first, then its bank; oldest first."""
    cur.execute("""
        UPDATE blood_units SET status = 'used', used_date = CURRENT_DATE, location = %s
        WHERE unit_id IN (
            SELECT unit_id FROM blood_units
            WHERE status = 'available' AND blood_type = %s AND location IN (%s, %s)
            ORDER BY (location = %s) DESC, expiry_date
            LIMIT %s)
    """, (hospital, blood_type, hospital, bank, hospital, n))
    return cur.rowcount


def add_donations(cur, bank, blood_type, n):
    for _ in range(n):
        cur.execute("""
            INSERT INTO blood_units (unit_id, blood_type, bank, location,
                                     collection_date, expiry_date, status)
            SELECT 'U-' || LPAD((COALESCE(MAX(SUBSTRING(unit_id FROM 3)::int), 0) + 1)::text, 5, '0'),
                   %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 42, 'available'
            FROM blood_units
        """, (blood_type, bank, bank))


def tick(cur):
    used = donated = 0
    cur.execute("""UPDATE blood_units SET status = 'expired'
                   WHERE status = 'available' AND expiry_date <= CURRENT_DATE""")
    expired = cur.rowcount
    for hospital, (per_day, bank) in HOSPITALS.items():
        for t, share in DEMAND.items():
            per_tick = per_day * share * HOURS_PER_TICK / 24
            used += use_bags(cur, hospital, bank, t, poisson(per_tick))
            donated_now = poisson(per_tick * SUPPLY[t])
            add_donations(cur, bank, t, donated_now)
            donated += donated_now
    return used, donated, expired


def main():
    load_dotenv()
    uri = os.environ.get("AIVEN_PG_URI")
    if not uri:
        raise SystemExit("AIVEN_PG_URI is missing from the .env file")

    sim_hour = 0
    with psycopg.connect(uri, autocommit=False) as conn:
        while True:
            with conn.cursor() as cur:
                used, donated, expired = tick(cur)
                conn.commit()
                sim_hour += HOURS_PER_TICK
                cur.execute("SELECT blood_type, units_available, days_of_supply, status "
                            "FROM stock_by_type")
                line = "  ".join(f"{t} {u} ({d}d {s})" if s != "OK" else f"{t} {u}"
                                 for t, u, d, s in cur.fetchall())
                print(f"[+{sim_hour:>3}h] used {used}, donated {donated}, expired {expired} | {line}",
                      flush=True)
            time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
