from fastapi.testclient import TestClient
import pytest
from blood_assessment.dashboard import create_dashboard
from blood_assessment.integration.store import Store

@pytest.fixture
def client(tmp_path):
    (tmp_path/'index.html').write_text('<html>BloodFlow</html>')
    app=create_dashboard(Store('sqlite:///'+str(tmp_path/'audit.sqlite')),tmp_path)
    with TestClient(app) as c:
        yield c

def test_session_origin_and_explicit_approval(client):
    assert client.get('/ui/state').status_code==401
    client.get('/')
    state=client.get('/ui/state').json()
    assert state['plan'] is None
    body={'assessment_id':state['assessment']['assessment_id'],'confirmed':True}
    assert client.post('/ui/optimize',json=body).status_code==403
    headers={'origin':'http://testserver'}
    assert client.post('/ui/optimize',json={**body,'confirmed':False},headers=headers).status_code==422
    result=client.post('/ui/optimize',json=body,headers=headers)
    assert result.status_code==200
    assert result.json()['summary']['total_met']==317
    assert client.post('/ui/optimize',json=body,headers=headers).json()==result.json()
    assert client.get('/ui/state?scenario=additive_stress').json()['plan'] is None

def test_chat_cites_saved_evidence_and_rejects_other_assessment(client,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    client.get('/')
    a=client.get('/ui/state').json()['assessment']['assessment_id']
    body={'assessment_id':a,'question':'Why does H1 need O-?'}
    headers={'origin':'http://testserver'}
    r=client.post('/ui/chat',json=body,headers=headers)
    assert r.status_code==200
    assert '14 units' in r.json()['answer'] and r.json()['evidence_refs']
    assert r.json()['mode']=='offline evidence'
    assert client.post('/ui/chat',json={**body,'assessment_id':'wrong'},headers=headers).status_code==404
    assert client.post('/ui/chat',json={**body,'live':True},headers=headers).status_code==409
    assert client.get('/ui/state',headers={'host':'evil.example'}).status_code==400

def test_reserve_explanation_counts_units_not_groups(client):
    client.get('/')
    identity=client.get('/ui/state').json()['assessment']['assessment_id']
    headers={'origin':'http://testserver'}
    plan=client.post('/ui/optimize',json={'assessment_id':identity,'confirmed':True},headers=headers).json()
    expected=sum(map(len,plan['inputs']['protected_reserve_unit_ids'].values()))
    reply=client.post('/ui/chat',json={'assessment_id':identity,'question':'How are reserves protected?'},headers=headers).json()
    assert f'protects {expected} units' in reply['answer']

def test_generated_scenario_isolated_reproducible_and_approval_gated(client):
    client.get('/')
    base=client.get('/ui/state').json()
    headers={'origin':'http://testserver'}
    request={'kind':'mixed','seed':42,'planning':'floor'}
    assert client.post('/ui/simulate',json=request).status_code==403
    result=client.post('/ui/simulate',json=request,headers=headers)
    assert result.status_code==200
    generated=result.json()
    assert generated['plan'] is None
    assert generated['assessment']['snapshot_id']!=base['assessment']['snapshot_id']
    assert generated['simulation']['seed']==42
    assert generated['quality']['valid']
    assert client.post('/ui/simulate',json=request,headers=headers).json()==generated
    identity=generated['assessment']['assessment_id']
    assert client.get('/ui/state',params={'assessment_id':identity}).json()==generated
    plan=client.post('/ui/optimize',json={'assessment_id':identity,'confirmed':True},headers=headers).json()
    assert plan['snapshot_id']==generated['assessment']['snapshot_id']
    assert client.get('/ui/state').json()==base


def test_generator_preserves_history_and_base():
    from pathlib import Path
    from blood_assessment.data_access.snapshot import from_csv,digest
    from blood_assessment.synthetic import generate
    snapshot=from_csv(Path(__file__).resolve().parents[2]/'data/raw/team_bundle','2026-10-22T12:00:00+02:00')
    original=digest(snapshot.tables)
    for kind in ('demand_surge','donation','mixed'):
        generated,meta=generate(snapshot,123,kind)
        assert digest(snapshot.tables)==original
        assert generated.tables['daily_usage']==snapshot.tables['daily_usage']
        assert generated.tables['transfers']==snapshot.tables['transfers']
        assert len(generated.tables['units'])>=len(snapshot.tables['units'])
        assert generated.snapshot_id==generate(snapshot,123,kind)[0].snapshot_id
        assert generated.snapshot_id!=generate(snapshot,124,kind)[0].snapshot_id


def test_live_chat_uses_generated_snapshot(client,monkeypatch):
    import blood_assessment.agent.data_agent as agent
    seen=[]
    async def fake_run(snapshot,store,key,question):
        seen.append(snapshot.snapshot_id)
        return {'tool_calls':[],'answer':{}}
    monkeypatch.setattr(agent,'run_data_agent',fake_run)
    monkeypatch.setenv('OPENAI_API_KEY','test-placeholder')
    monkeypatch.setenv('OPENAI_MODEL','test-model')
    client.get('/')
    headers={'origin':'http://testserver'}
    generated=client.post('/ui/simulate',json={'kind':'donation','seed':13},headers=headers).json()
    reply=client.post('/ui/chat',json={'assessment_id':generated['assessment']['assessment_id'],'question':'H1 O- stock?','live':True},headers=headers)
    assert reply.status_code==200
    assert seen==[generated['assessment']['snapshot_id']]
