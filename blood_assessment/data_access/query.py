"""Bounded read-only SQL over a single validated, isolated snapshot.

Model SQL never reaches the operational connection. SQLite's authorizer enforces
access at execution time, rather than trusting SELECT-prefix/regex checks.
"""
import sqlite3
import time
from threading import Lock
from blood_assessment.data_access.snapshot import make_snapshot
from blood_assessment.data_access.validation import validate

COLUMNS = {
    'sites': {'site_id':'TEXT','type':'TEXT','name':'TEXT','address':'TEXT','arrondissement':'INTEGER','lat':'REAL','lon':'REAL','trauma_level':'INTEGER','beds':'INTEGER','avg_daily_rbc_units':'INTEGER','home_bank_id':'TEXT'},
    'units': {'unit_id':'TEXT','blood_type':'TEXT','storage_site':'TEXT','collection_date':'TEXT','expiry_date':'TEXT','status':'TEXT','used_date':'TEXT','is_synthetic':'INTEGER'},
    'transfers': {'transfer_id':'TEXT','unit_id':'TEXT','from_site_id':'TEXT','to_site_id':'TEXT','transfer_date':'TEXT','reason':'TEXT'},
    'daily_usage': {'date':'TEXT','site_id':'TEXT','blood_type':'TEXT','units_used':'INTEGER','partial_day':'INTEGER'},
    'planned_activity': {'activity_id':'TEXT','site_id':'TEXT','date':'TEXT','procedure':'TEXT','blood_type':'TEXT','units_expected':'INTEGER','priority':'TEXT'},
    'travel_times': {'from_site_id':'TEXT','to_site_id':'TEXT','distance_km':'REAL','minutes_normal':'INTEGER','minutes_rush':'INTEGER'},
}
FUNCTIONS = {'count','sum','avg','min','max','round','abs','coalesce','nullif','ifnull','lower','upper','length','substr','like','date','julianday'}

class SnapshotSQL:
    def __init__(self, snapshot):
        self.snapshot=make_snapshot(snapshot.tables,snapshot.as_of,snapshot.dataset_schema,snapshot.source)
        if self.snapshot.snapshot_id != snapshot.snapshot_id:
            raise ValueError('Snapshot fingerprint mismatch')
        self.quality=validate(self.snapshot)
        self.lock=Lock()
        self.db=sqlite3.connect(':memory:',check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,100_000)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,8000)
        for table, columns in COLUMNS.items():
            declaration=', '.join(f'"{k}" {v}' for k,v in columns.items())
            self.db.execute(f'CREATE TABLE "{table}" ({declaration})')
            rows=[]
            for row in self.snapshot.tables[table]:
                values=[]
                for column in columns:
                    value=row.get(column)
                    if column in ('partial_day','is_synthetic') and value is not None:
                        value=int(str(value).lower()=='true')
                    values.append(value)
                rows.append(values)
            placeholders=','.join('?' for _ in columns)
            self.db.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})',rows)
        self.db.commit()
        self.db.execute('PRAGMA query_only=ON')
        self.db.set_authorizer(self._authorize)

    @staticmethod
    def _authorize(action,arg1,arg2,database,trigger):
        if action==sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_READ and database=='main' and arg1 in COLUMNS:
            return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in FUNCTIONS:
            return sqlite3.SQLITE_OK
        # This also blocks recursive CTEs, PRAGMA, ATTACH, schema access, writes,
        # transaction control, load_extension, and unapproved functions.
        return sqlite3.SQLITE_DENY

    def schema(self):
        return {'dialect':'SQLite','tables':COLUMNS,'functions':sorted(FUNCTIONS),'row_limit':200,'parameters':'Positional ? bindings; booleans are 0/1; dates are ISO text.','restrictions':'Read only, six tables, non-recursive queries, no operational DB access.'}

    def execute(self, sql, parameters=(), max_rows=100):
        if not 1<=max_rows<=200 or len(sql)>8000 or len(parameters)>50:
            raise ValueError('Query bounds exceeded')
        deadline=time.monotonic()+1.0
        steps=0
        def stop():
            nonlocal steps
            steps+=1000
            return int(steps>200_000 or time.monotonic()>deadline)
        with self.lock:
            self.db.set_progress_handler(stop,1000)
            try:
                cursor=self.db.execute(sql,parameters)
                if cursor.description is None: raise ValueError('A result-producing SELECT is required')
                columns=[d[0] for d in cursor.description]
                if len(columns)!=len(set(columns)):
                    raise ValueError('Use unique column aliases')
                rows=cursor.fetchmany(max_rows+1)
                return {'rows':[dict(r) for r in rows[:max_rows]],'truncated':len(rows)>max_rows,'returned_rows':min(len(rows),max_rows)}
            except sqlite3.Error as exc:
                raise ValueError('SQL rejected or query budget exceeded: '+str(exc)) from None
            finally:
                self.db.set_progress_handler(None,0)

    def close(self):
        self.db.close()
