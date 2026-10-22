# Blood storage: shared setup

Use the root [integration guide](../docs/INTEGRATION.md). The active CSVs are in `../data/canonical/`. The original uploaded scripts and older stock file are preserved under `../data/raw/`; do not load them together with the canonical ledger.

## Offline

From the repository root:

```sh
python tools/build_dataset.py
python -m blood_response validate
python blood-storage/load_blood_data.py --validate-only
python blood-storage/simulate_live.py --ticks 24 --seed 42 --output runs/storage-demo
```

The compatibility script names remain, but use the same shared implementation. Simulation is offline by default. All paths are resolved from the repository rather than the terminal's working directory.

## Optional Aiven/PostgreSQL

```sh
python -m pip install -r blood-storage/requirements.txt
```

Copy `.env.example` to `blood-storage/.env` locally and supply your own `AIVEN_PG_URI`, or set it in the environment. Credentials are never included in the repository.

```sh
python blood-storage/load_blood_data.py --schema blood_demo
python blood-storage/simulate_live.py --database --schema blood_demo --ticks 24 --interval 10
```

Use `--reset` on the load command only when intentionally replacing this module's existing demo objects in that schema. It refuses the public and system schemas. Creation/COPY/reset occur in one transaction; failures roll back. No CASCADE is used. Only one simulator should write a scenario at a time.

The database contract uses `blood_demo.sites`, `units`, `transfers`, `daily_usage`, `planned_activity`, `travel_times`, and `simulation_clock`. Views are `blood_demo.blood_stock`, `stock_by_site`, and `stock_by_type`. Query with the schema prefix or set your session search path explicitly. Do not expect the older unqualified `public.blood_units` schema or name-based location columns.

Views use the persisted simulation clock in Europe/Paris, not CURRENT_DATE. Stock summaries expose all groups, and unknown usage does not become OK. Database commands are optional: none is needed for the offline planner or social replay. A real database integration run is still required before relying on the PostgreSQL adapter.
