from copy import deepcopy
from datetime import timedelta
from itertools import product
from pathlib import Path
import pytest
from ortools.sat.python import cp_model
from blood_assessment.contracts import Policy,GROUPS
from blood_assessment.data_access.snapshot import from_csv,digest
from blood_assessment.integration.store import Store
from blood_assessment.service import Service,build
from blood_assessment.optimization.adapter import prepare_problem,graph_preview
from blood_assessment.optimization.solver import solve,validate_solution,lexicographic

@pytest.fixture(scope='module')
def setup():
    s=from_csv(Path(__file__).resolve().parents[2]/'data/raw/team_bundle','2026-10-22T12:00:00+02:00')
    p=Policy(exposure_elapsed=.5,reserves={f'{b}/{g}':2 for b in ('B1','B2') for g in GROUPS})
    return s,p,build(s,p)[2]

def small_problem():
    return {'allocation_date':'2026-10-23','config':{'max_seconds_per_stage':2,'allow_unmet_demand':True},
            'lots':[{'site_id':'B1','type':'blood_bank','blood_type':'O-','expiry_date':'2026-10-24','expiry_rank':1,'unit_ids':['u1']},
                    {'site_id':'B2','type':'blood_bank','blood_type':'O-','expiry_date':'2026-10-26','expiry_rank':3,'unit_ids':['u2']}],
            'demands':[{'site_id':'H1','blood_type':'O-','date':'2026-10-23','units':1,'priority_score':100},
                       {'site_id':'H2','blood_type':'O-','date':'2026-10-24','units':1,'priority_score':0}],
            'routes':[{'from_site_id':b,'to_site_id':h,'distance_km':d,'distance_metres':d*1000,'minutes':10} for b,h,d in [('B1','H1',3),('B1','H2',1),('B2','H1',1),('B2','H2',3)]]}

def test_independently_enumerated_lexicographic_optimum():
    p=small_problem();r=solve(p)
    distances={(x['from_site_id'],x['to_site_id']):x['distance_metres'] for x in p['routes']}
    candidates=[]
    for assignments in product([-1,0,1],repeat=2):
        met=[0,0];dist=0;expiry=0;valid=True
        for lot,dest in zip(p['lots'],assignments):
            if dest<0:continue
            d=p['demands'][dest]
            if lot['expiry_date']<=d['date']:valid=False;break
            met[dest]+=1;dist+=distances[lot['site_id'],d['site_id']];expiry+=lot['expiry_rank']
        if not valid or any(m>1 for m in met):continue
        u=[1-m for m in met]
        candidates.append((200*u[0]+100*u[1],2*u[0]+u[1],dist,expiry))
    assert tuple(stage['value'] for stage in r['stages'])==min(candidates)
    assert r['solver_status']=='OPTIMAL' and r['summary']['total_unmet']==0
    validate_solution(p,r)

def test_expiry_changes_feasible_assignment():
    p=small_problem();r=solve(p)
    by_unit={uid:a for a in r['assignments'] for uid in a['unit_ids']}
    assert by_unit['u1']['site_id']=='H1'
    assert by_unit['u2']['site_id']=='H2'
    assert all(a['expiry_date']>a['requirement_date'] for a in r['assignments'])

def test_priorities_under_scarcity():
    p=small_problem();p['lots']=p['lots'][1:]
    r=solve(p)
    assert r['demand_results'][0]['met']==1
    assert r['demand_results'][1]['unmet']==1
    p['demands'][0]['priority_score']=0;p['demands'][1]['priority_score']=100
    r2=solve(p)
    assert r2['demand_results'][1]['met']==1

def test_earlier_requirement_breaks_equal_priority_tie():
    p=small_problem();p['lots']=p['lots'][1:]
    for d in p['demands']:d['priority_score']=50
    assert solve(p)['demand_results'][0]['met']==1

def test_route_absence_blocks_allocation():
    p=small_problem();p['routes']=[]
    r=solve(p)
    assert r['summary']['total_unmet']==2 and not r['transfer_proposals']

def test_no_substitution_or_hospital_transshipment():
    p=small_problem();p['lots'][0]['blood_type']='A+'
    p['lots'][1].update(site_id='H2',type='hospital')
    r=solve(p)
    assert r['demand_results'][0]['unmet']==1
    assert r['summary']['total_transferred']==0

def test_explicit_infeasibility_no_phantom_results():
    p=small_problem();p['lots']=[];p['config']['allow_unmet_demand']=False
    r=solve(p)
    assert r['solver_status']=='INFEASIBLE'
    assert r['summary'] is None and r['transfer_proposals']==[]

def test_later_solver_failure_preserves_valid_incumbent():
    model=cp_model.CpModel();v=model.new_int_var(0,3,'x')
    factories=[]
    class Wrapper:
        def __init__(self):
            self.real=cp_model.CpSolver();self.parameters=self.real.parameters
            self.number=len(factories);factories.append(self)
        def solve(self,model):return self.real.solve(model) if self.number==0 else cp_model.UNKNOWN
        def value(self,x):return self.real.value(x)
        def status_name(self,s):return self.real.status_name(s)
    values,stages,status=lexicographic(model,[('first',v),('second',3-v)],{'x':v},1,Wrapper)
    assert values=={'x':0} and status=='FEASIBLE_PREVIOUS_STAGE'
    assert stages[0]['optimal'] and not stages[1]['optimal']

def test_first_solver_failure_no_incumbent():
    class Unknown:
        def __init__(self):
            from types import SimpleNamespace
            self.parameters=SimpleNamespace()
        def solve(self,model):return cp_model.UNKNOWN
        def status_name(self,s):return 'UNKNOWN'
    model=cp_model.CpModel();v=model.new_int_var(0,1,'x')
    values,stages,status=lexicographic(model,[('first',v)],{'x':v},1,Unknown)
    assert values is None and status=='UNKNOWN'

def test_actual_dataset_dated_targets_and_reserves(setup):
    s,p,a=setup;before=digest(s.tables)
    problem=prepare_problem(s,a,p);r=graph_preview(s,a,p)
    assert r['solver_status']=='OPTIMAL'
    assert r['summary']['total_requirement']==sum(x.target for x in a.proposed_requirement_updates)
    protected={uid for ids in problem['protected_reserve_unit_ids'].values() for uid in ids}
    sent=[uid for row in r['transfer_proposals'] for uid in row['unit_ids']]
    assert not protected.intersection(sent) and len(sent)==len(set(sent))
    assert digest(s.tables)==before
    assert all('X1'!=x['from_site_id'] for x in r['transfer_proposals'])
    assert all(sum(x['units'] for x in req.components['dated_requirements'])==req.target for req in a.proposed_requirement_updates)

def test_expiry_preference_after_transport():
    p=small_problem();p['demands']=p['demands'][:1]
    p['lots'][1]['site_id']='B1'
    r=solve(p)
    assert r['transfer_proposals'][0]['unit_ids']==['u1']

def test_unknown_today_and_late_snapshot_blocked_routes(setup):
    s,p,a=setup
    from blood_assessment.data_access.snapshot import make_snapshot
    late=make_snapshot(s.tables,'2026-10-22T23:59:00+02:00',source=s.source)
    _,_,assessment=build(late,p)
    problem=prepare_problem(late,assessment,p)
    assert problem['routes']==[]
    assert all(r['reason']=='cannot_arrive_before_first_planning_day' for r in problem['blocked_routes'])

def test_tampered_dated_requirements_rejected(setup):
    s,p,a=setup;a=a.model_copy(deep=True)
    a.proposed_requirement_updates[0].components['dated_requirements'][0]['units']+=1
    with pytest.raises(ValueError,match='approved target'):prepare_problem(s,a,p)

def test_solution_validator_rejects_reused_unit():
    p=small_problem();r=solve(p)
    r['assignments'][1]['unit_ids']=r['assignments'][0]['unit_ids']
    with pytest.raises(ValueError):validate_solution(p,r)

def test_reproducible_flows():
    a,b=solve(small_problem()),solve(small_problem())
    assert a['transfer_proposals']==b['transfer_proposals']
    assert a['assignments']==b['assignments']
    assert a['stages']==b['stages']

def test_api_graph_replay_and_approval(setup,tmp_path,monkeypatch):
    from blood_assessment.integration.api import create_app
    from fastapi.testclient import TestClient
    s,p,a=setup;svc=Service(Store('sqlite:///'+str(tmp_path/'graph.sqlite')))
    a=svc.assess(s,p,'assessment')
    d=svc.approve(a.assessment_id,'human','approved','approval')
    result=svc.optimize(a.assessment_id,d['approval_id'],'solve')
    assert svc.optimize(a.assessment_id,d['approval_id'],'solve')==result
    monkeypatch.setenv('ASSESSMENT_API_TOKEN','client')
    client=TestClient(create_app(svc));url='/optimization/'+result['optimizer_run_id']
    assert client.get(url).status_code==401
    assert client.get(url+'/graph',headers={'Authorization':'Bearer client'}).json()==result['graph']
    assert client.get(url,headers={'Authorization':'Bearer client'}).json()==result
