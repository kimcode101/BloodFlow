"""Append-only application audit records, separate from operational tables."""
from sqlalchemy import create_engine, MetaData, Table, Column, String, JSON, select
from sqlalchemy.exc import IntegrityError
from blood_assessment.data_access.snapshot import digest

class Store:
    def __init__(self, url='sqlite:///runs/assessment-audit.sqlite'):
        self.engine=create_engine(url)
        meta=MetaData()
        self.records=Table('blood_assessment_records_v1',meta,Column('id',String(64),primary_key=True),Column('kind',String(40),nullable=False),Column('request_key',String(200),unique=True,nullable=False),Column('request_hash',String(64),nullable=False),Column('payload',JSON,nullable=False))
        meta.create_all(self.engine)

    def put(self, kind, key, request, payload):
        identity=digest([kind,key]); request_hash=digest(request)
        try:
            with self.engine.begin() as conn:
                conn.execute(self.records.insert().values(id=identity,kind=kind,request_key=kind+':'+key,request_hash=request_hash,payload=payload))
        except IntegrityError:
            with self.engine.connect() as conn:
                row=conn.execute(select(self.records).where(self.records.c.id==identity)).mappings().one()
                if row['request_hash']!=request_hash: raise ValueError('Idempotency key reused with different input')
                return row['payload']
        return payload

    def get(self, kind, key):
        with self.engine.connect() as conn:
            row=conn.execute(select(self.records.c.payload).where(self.records.c.id==digest([kind,key]))).first()
        if row is None: raise KeyError(key)
        return row[0]

    def lookup(self, kind, key, request):
        with self.engine.connect() as conn:
            row=conn.execute(select(self.records).where(self.records.c.id==digest([kind,key]))).mappings().first()
        if row is None: return None
        if row['request_hash']!=digest(request): raise ValueError('Idempotency key reused with different input')
        return row['payload']
