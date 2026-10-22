"""Read-only source adapters. No operational SQL writes exist in this package."""
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, text
from blood_assessment.contracts import Snapshot

TABLES = ('sites', 'travel_times', 'units', 'transfers', 'daily_usage', 'planned_activity')

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()

def make_snapshot(tables, as_of, schema='public', source='fixture'):
    if schema not in ('public', 'kim'):
        raise ValueError('Only configured public and kim schemas are allowed')
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('Timezone-aware as_of required')
    as_of = as_of.astimezone(ZoneInfo('Europe/Paris'))
    # Canonicalize database dates/booleans and CSV strings identically.
    tables = {t: sorted([{k: None if v is None or v == '' else str(v) for k, v in r.items()} for r in tables[t]], key=lambda r: json.dumps(r, sort_keys=True)) for t in TABLES}
    h = digest(tables)
    sid = digest({'hash': h, 'schema': schema, 'as_of': as_of.isoformat(), 'source': source})
    return Snapshot(snapshot_id=sid, dataset_schema=schema, as_of=as_of, source=source, tables=tables, data_hash=h)

def from_csv(folder, as_of, schema='public'):
    tables = {}
    for t in TABLES:
        with (Path(folder) / f'{t}.csv').open() as f:
            tables[t] = list(csv.DictReader(f))
    return make_snapshot(tables, as_of, schema, 'source_csv_fixture')

def from_postgres(url, as_of, schema='public'):
    if schema not in ('public', 'kim'):
        raise ValueError('Schema not allowed')
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    engine = create_engine(url, isolation_level='REPEATABLE READ', connect_args={'connect_timeout': 10})
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text('SET TRANSACTION READ ONLY'))
            tables = {t: [dict(r) for r in conn.execute(text(f'SELECT * FROM "{schema}"."{t}"')).mappings()] for t in TABLES}
        return make_snapshot(tables, as_of, schema, 'postgresql_read_only_repeatable_read')
    finally:
        engine.dispose()
