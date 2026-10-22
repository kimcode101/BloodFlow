import asyncio
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from blood_assessment.contracts import Policy, GROUPS, AgentReview
from blood_assessment.data_access.snapshot import from_csv, make_snapshot, digest
from blood_assessment.data_access.validation import validate, DataError
from blood_assessment.forecasting.models import panel, baseline, compare, poisson, features
from blood_assessment.forecasting.run import run
from blood_assessment.inventory.projection import project, usable, target
from blood_assessment.integration.store import Store
from blood_assessment.integration.api import create_app
from blood_assessment.service import Service, build, validate_review
from blood_assessment.agent.assessment import create_agent, run_agent

ROOT=Path(__file__).resolve().parents[2]
AS_OF='2026-10-22T12:00:00+02:00'
@pytest.fixture(scope='module')
def snapshot(): return from_csv(ROOT/'data/raw/team_bundle',AS_OF)
@pytest.fixture(scope='module')
def policy(): return Policy(exposure_elapsed=.5,reserves={f'{b}/{g}':2 for b in ('B1','B2') for g in GROUPS})
@pytest.fixture(scope='module')
def built(snapshot,policy): return build(snapshot,policy)
@pytest.fixture
def service(tmp_path): return Service(Store('sqlite:///'+str(tmp_path/'audit.sqlite')))

def test_totals_reconciliation_no_double_counting(snapshot):
    q=validate(snapshot)
    assert q['totals']['used']==761 and q['totals']['available']==777
    assert sum(int(r['units_used']) for r in snapshot.tables['daily_usage'])==761
    assert q['totals']['daily_usage']==163 and q['totals']['transfers']==981

def test_partial_and_zero_completion(snapshot):
    p=panel(snapshot,validate(snapshot))
    assert len(p)==6*4*8 and p.date.max()=='2026-10-21'
    assert p.units_used.sum()<761
    assert (p.units_used==0).any()

def test_missing_nonzero_is_not_zero(snapshot):
    s=snapshot.model_copy(deep=True)
    s.tables['daily_usage'].pop(0)
    with pytest.raises(DataError,match='reconcile'): validate(s)

def test_unverified_missing_not_filled(snapshot):
    q=validate(snapshot); q['sparse_reconciled']=False
    assert len(panel(snapshot,q))<192

@pytest.mark.parametrize('table', ['units','transfers','planned_activity','daily_usage','travel_times','sites'])
def test_duplicates(snapshot,table):
    s=snapshot.model_copy(deep=True); s.tables[table].append(s.tables[table][0].copy())
    with pytest.raises(DataError,match='duplicate'): validate(s)

def test_unresolved_planned(snapshot,policy):
    s=snapshot.model_copy(deep=True)
    p=next(r for r in s.tables['planned_activity'] if r['site_id']=='H1' and r['blood_type']=='O-' and r['date']=='2026-10-23')
    p['units_expected']=None
    q=validate(s)
    assert 'planned_activity/'+p['activity_id'] in q['unresolved_planned']
    f=run(s,q,policy)
    assert next(r for r in f['records'] if r['site_id']=='H1' and r['blood_type']=='O-')['known_scheduled_units']==0

def test_floor_scenario_and_intervals(built):
    q,f,a=built
    r=next(r for r in f['records'] if r['site_id']=='H1' and r['blood_type']=='O-')
    assert r['known_scheduled_units']==8
    assert r['proposed_requirement']==max(8,r['expected_consumption'])
    assert r['proposed_requirement']<8+r['expected_consumption']
    assert r['forecast_interval']==['2026-10-23T00:00:00+02:00','2026-10-24T00:00:00+02:00']
    assert f['comparison']['ml_status']=='insufficient_history'
    assert len(f['records'])==14*32
    for r in f['records']: assert 0<=r['uncertainty_range'][0]<=r['expected_consumption']<=r['uncertainty_range'][1]

def test_whole_dates_no_leakage(snapshot,policy):
    df=panel(snapshot,validate(snapshot)); c=compare(df,policy)
    assert c['metrics']['mean']['observations']==3*32
    for fold in c['metrics']['mean']['fold_dates']: assert fold['train_end']<fold['test_date']
    train=df[df.date<'2026-10-20']; keys=[('H1','O-')]
    original=features(train,keys)
    changed=df.copy(); changed.loc[changed.date>='2026-10-20','units_used']=999999
    pd.testing.assert_frame_equal(original,features(changed[changed.date<'2026-10-20'],keys))

def test_determinism(snapshot,policy,built):
    assert run(snapshot,validate(snapshot),policy)==built[1]

def test_sparse_and_all_zero(snapshot,policy):
    df=panel(snapshot,validate(snapshot)); df['units_used']=0.
    for m in ('mean','last','ewm'):
        assert baseline(df,[('H1','O-')],m,policy)[0]==0
    assert poisson(df,[('H1','O-')])[0]==0
    assert compare(df,policy)['metrics']['mean']['wape'] is None
    df.loc[(df.site_id=='H2')&(df.blood_type=='O-'),'units_used']=4
    assert baseline(df,[('H1','O-')],'last',policy)[0]>0

def test_pooled_ml_long_synthetic_only(policy):
    # Synthetic test panel, not evidence for supplied dataset accuracy.
    df=pd.DataFrame([{'date':d.date().isoformat(),'site_id':h,'blood_type':b,'units_used':float((i+j)%4)} for i,d in enumerate(pd.date_range('2026-01-01',periods=18)) for j,(h,b) in enumerate([('H1','O-'),('H2','A+')])])
    pred=poisson(df,[('H1','O-'),('H2','A+')])
    assert np.isfinite(pred).all() and (pred>=0).all()
    c=compare(df,policy)
    assert c['metrics']['poisson']['folds']==4

def test_exclusive_expiry_fefo_and_nonnegative():
    units=[{'unit_id':'1','expiry_date':'2026-10-23'},{'unit_id':'2','expiry_date':'2026-10-24'},{'unit_id':'3','expiry_date':'2026-10-25'}]
    p=project(units,[(date(2026,10,22),1),(date(2026,10,23),1),(date(2026,10,24),3)])
    assert p['units_expiring_unused']==0
    assert p['unmet_demand']==2
    assert all(r['usable_closing_inventory']>=0 for r in p['days'])
    p=project(units,[(date(2026,10,23),0)])
    assert p['units_expiring_unused']==1

def test_no_future_receipts(snapshot,policy,built):
    s=snapshot.model_copy(deep=True); s.tables['transfers']=[]
    assert build(s,policy)[2].findings==built[2].findings

def test_idempotency_approval_no_mutation(service,snapshot,policy):
    before=digest(snapshot.tables)
    a=service.assess(snapshot,policy,'k')
    assert service.assess(snapshot,policy,'k')==a
    with pytest.raises(ValueError,match='Idempotency'): service.assess(snapshot,Policy(),'k')
    rejected=service.approve(a.assessment_id,'reviewer','rejected','reject')
    with pytest.raises(ValueError,match='approval'): service.optimize(a.assessment_id,rejected['approval_id'],'p')
    approved=service.approve(a.assessment_id,'reviewer','approved','approve')
    p=service.optimize(a.assessment_id,approved['approval_id'],'p')
    assert p==service.optimize(a.assessment_id,approved['approval_id'],'p')
    ids=[u for t in p['transfer_proposals'] for u in t['unit_ids']]
    assert len(ids)==len(set(ids))
    units={u['unit_id']:u for u in snapshot.tables['units']}
    for t in p['transfer_proposals']:
        assert all(units[u]['blood_type']==t['blood_type'] for u in t['unit_ids'])
    assert digest(snapshot.tables)==before

def test_reserves_required(service,snapshot):
    a=service.assess(snapshot,Policy(),'a'); d=service.approve(a.assessment_id,'reviewer','approved','d')
    with pytest.raises(ValueError,match='reserves'): service.optimize(a.assessment_id,d['approval_id'],'p')

def test_cross_assessment_approval(service,snapshot,policy):
    a=service.assess(snapshot,policy,'a'); b=service.assess(snapshot,Policy(),'b')
    d=service.approve(a.assessment_id,'reviewer','approved','d')
    with pytest.raises(ValueError,match='approval'): service.optimize(b.assessment_id,d['approval_id'],'p')

def test_agent_numerical_validation(built):
    a=built[2]; r=a.findings[0]
    good={'claims':[{'evidence_ref':r['evidence_ref'],'field':'stock','value':r['stock']}],'finding_refs':[r['evidence_ref']],'next_action':'request_review'}
    validate_review(good,a)
    good['claims'][0]['value']+=1
    with pytest.raises(ValueError,match='differs'): validate_review(good,a)


def test_mock_agent_and_failure(service,snapshot,policy,monkeypatch):
    monkeypatch.setenv('OPENAI_MODEL','configured-test-model')
    a=service.assess(snapshot,policy,'a')
    async def fake(*args,**kwargs): return SimpleNamespace(final_output=AgentReview(claims=[],finding_refs=[a.evidence_refs[0]],next_action='request_review'))
    result=asyncio.run(run_agent(service,a.assessment_id,'mock',fake))
    assert result['review']['next_action']=='request_review'
    async def broken(*args,**kwargs): raise RuntimeError('simulated failure')
    with pytest.raises(RuntimeError): asyncio.run(run_agent(service,a.assessment_id,'broken',broken))
    with pytest.raises(KeyError): service.store.get('agent_review','broken')
    async def malformed(*args,**kwargs): return SimpleNamespace(final_output={'unexpected':True})
    with pytest.raises(ValueError): asyncio.run(run_agent(service,a.assessment_id,'bad',malformed))
    assert service.store.get('assessment',a.assessment_id)['assessment']==a.model_dump(mode='json')

def test_api_auth_validation_approval(service,snapshot,policy,monkeypatch):
    monkeypatch.setenv('ASSESSMENT_API_TOKEN','client'); monkeypatch.setenv('ASSESSMENT_REVIEW_TOKEN','review'); monkeypatch.setenv('ASSESSMENT_REVIEWER','human')
    c=TestClient(create_app(service)); headers={'Authorization':'Bearer client'}
    body={'as_of':AS_OF,'policy':policy.model_dump(),'idempotency_key':'api'}
    assert c.post('/assessments',json=body).status_code==401
    response=c.post('/assessments',json=body,headers=headers); assert response.status_code==200,response.text
    aid=response.json()['assessment_id']
    assert c.post('/assessments',json={**body,'dataset_schema':'public;DROP TABLE units'},headers=headers).status_code==422
    url=f'/assessments/{aid}/approvals'
    assert c.post(url,json={'decision':'approved','idempotency_key':'d'},headers=headers).status_code==403
    d=c.post(url,json={'decision':'approved','idempotency_key':'d'},headers={'Authorization':'Bearer review'})
    assert d.status_code==200
    assert c.post(f'/assessments/{aid}/proposals',json={'approval_id':d.json()['approval_id'],'idempotency_key':'p'},headers=headers).status_code==200

def test_schema_and_timezone(snapshot):
    with pytest.raises(ValueError): make_snapshot(snapshot.tables,AS_OF,'evil')
    with pytest.raises(ValueError): make_snapshot(snapshot.tables,'2026-10-22T12:00:00')
    other=make_snapshot(snapshot.tables,AS_OF,'kim')
    assert other.snapshot_id!=snapshot.snapshot_id

@pytest.mark.skipif(__import__('os').getenv('RUN_LIVE_AGENT')!='1',reason='Opt-in live API test requires credentials and configured model')
def test_live_agent(service,snapshot,policy):
    a=service.assess(snapshot,policy,'live')
    assert asyncio.run(run_agent(service,a.assessment_id,'live'))['assessment_id']==a.assessment_id

def test_optimizer_contract_rejects_wrong_group(service,snapshot,policy):
    class BadSolver:
        def solve(self,inputs):
            u=next(u for u in inputs['eligible_units'] if u['storage_site']=='B1' and u['blood_type']=='O-')
            return [{'from_site_id':'B1','to_site_id':'H1','blood_type':'A+','units':1,'unit_ids':[u['unit_id']]}]
    service.optimizer=BadSolver()
    a=service.assess(snapshot,policy,'a'); d=service.approve(a.assessment_id,'human','approved','d')
    with pytest.raises(ValueError,match='Ineligible'): service.optimize(a.assessment_id,d['approval_id'],'p')

def test_postgres_readonly_snapshot_contract(snapshot,monkeypatch):
    from blood_assessment.data_access import snapshot as module
    statements=[]
    class Result:
        def __init__(self,rows): self.rows=rows
        def mappings(self): return self.rows
    class Conn:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def begin(self): return self
        def execute(self,sql):
            stmt=str(sql); statements.append(stmt)
            if stmt.startswith('SELECT'):
                name=stmt.split('.')[-1].strip('"')
                return Result(snapshot.tables[name])
    class Engine:
        def connect(self): return Conn()
        def dispose(self): pass
    def engine(url,**kwargs):
        assert kwargs['isolation_level']=='REPEATABLE READ'
        return Engine()
    monkeypatch.setattr(module,'create_engine',engine)
    s=module.from_postgres('postgresql://unused',AS_OF,'kim')
    assert statements[0]=='SET TRANSACTION READ ONLY'
    assert len(statements)==7 and all('"kim".' in x for x in statements[1:])
    assert s.dataset_schema=='kim'

def test_api_agent_failure_isolated(service,snapshot,policy,monkeypatch):
    from blood_assessment.integration import api
    monkeypatch.setenv('ASSESSMENT_API_TOKEN','test')
    a=service.assess(snapshot,policy,'a')
    async def fail(*args,**kwargs): raise RuntimeError('provider unavailable')
    monkeypatch.setattr(api,'run_agent',fail)
    c=TestClient(api.create_app(service))
    r=c.post(f'/assessments/{a.assessment_id}/agent',json={'idempotency_key':'bad'},headers={'Authorization':'Bearer test'})
    assert r.status_code==502
    assert service.store.get('assessment',a.assessment_id)['assessment']==a.model_dump(mode='json')

def test_expiry_mismatch_is_excluded(snapshot):
    s=snapshot.model_copy(deep=True)
    unit=next(u for u in s.tables['units'] if u['status']=='available')
    unit['expiry_date']='2026-10-22'
    # Remove movements for this unit so independently invalid historical expiry
    # chronology does not obscure the available-stock boundary being exercised.
    s.tables['transfers']=[r for r in s.tables['transfers'] if r['unit_id']!=unit['unit_id']]
    assert any('ineligible' in w for w in validate(s)['warnings'])
    assert unit not in usable(s,unit['storage_site'],unit['blood_type'],date(2026,10,22))

def test_calendar_timezone(snapshot):
    s=make_snapshot(snapshot.tables,'2026-10-21T23:00:00-03:00')
    assert s.as_of.date()==date(2026,10,22)
