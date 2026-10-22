import asyncio
import json
from pathlib import Path
import pytest
from agents import Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from blood_assessment.data_access.snapshot import from_csv,digest
from blood_assessment.agent.data_tools import DataTools
from blood_assessment.agent.data_agent import run_data_agent,checked_answer
from blood_assessment.integration.store import Store

@pytest.fixture
def snapshot():
    return from_csv(Path(__file__).resolve().parents[2]/'data/raw/team_bundle','2026-10-22T12:00:00+02:00')

@pytest.fixture
def runtime(snapshot):
    rt=DataTools(snapshot)
    yield rt
    rt.close()

FORECAST={'site_id':'H1','blood_type':'O-','horizon_days':2,'method':'mean','trailing_window':7,'smoothing_alpha':.4,'planning_policy':'floor'}
SQL={'sql':'SELECT COUNT(*) AS stock FROM units WHERE storage_site=? AND blood_type=? AND status=? AND expiry_date>?','parameters':['H1','O-','available','2026-10-22'],'max_rows':20}

def test_real_sql_numeric_types(runtime):
    r=runtime.query(SQL)
    assert r['values']['rows']==[{'stock':0}]
    p=runtime.query({'sql':'SELECT SUM(units_used) AS consumption FROM daily_usage','parameters':[],'max_rows':1})
    assert p['values']['rows'][0]['consumption']==761
    p=runtime.query({'sql':'SELECT SUM(units_used) AS consumption FROM daily_usage WHERE partial_day=0','parameters':[],'max_rows':1})
    assert p['values']['rows'][0]['consumption']<761

@pytest.mark.parametrize('sql',[
    'DELETE FROM units','UPDATE units SET status="used"','DROP TABLE units',
    'CREATE TABLE x (a TEXT)','INSERT INTO units (unit_id) VALUES ("evil")',
    "ATTACH DATABASE '/tmp/should-not-exist.db' AS other",'PRAGMA query_only=OFF',
    'SELECT name FROM sqlite_master','SELECT load_extension("x")',
    'SELECT randomblob(99999999)', 'SELECT * FROM pragma_table_info("units")',
    'SELECT * FROM units; DELETE FROM units',
    'WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT * FROM x',
    'SELECT * FROM kim.units',
])
def test_sql_rejects_unsafe_or_out_of_scope(runtime,sql):
    with pytest.raises(ValueError): runtime.query({'sql':sql,'parameters':[],'max_rows':2})
    assert runtime.query(SQL)['values']['rows']==[{'stock':0}]

def test_sql_join_and_bound_parameters(runtime):
    result=runtime.query({'sql':'SELECT s.name, COUNT(u.unit_id) AS stock FROM sites s LEFT JOIN units u ON u.storage_site=s.site_id AND u.status=? AND u.blood_type=? WHERE s.site_id=? GROUP BY s.name','parameters':['available','O-','B1'],'max_rows':5})
    assert result['values']['rows'][0]['stock']==22
    assert runtime.query({**SQL,'parameters':["H1' OR 1=1 --",'O-','available','2026-10-22']})['values']['rows'][0]['stock']==0

def test_sql_limits(runtime):
    r=runtime.query({'sql':'SELECT unit_id FROM units','parameters':[],'max_rows':2})
    assert r['values']['truncated'] and r['values']['returned_rows']==2
    with pytest.raises(ValueError): runtime.query({**SQL,'max_rows':201})
    with pytest.raises(ValueError,match='budget'):
        runtime.query({'sql':'SELECT count(*) FROM units a CROSS JOIN units b CROSS JOIN units c','parameters':[],'max_rows':1})

def test_forecast_recomputes_and_projection(runtime,snapshot):
    before=digest(snapshot.tables)
    f=runtime.forecast(FORECAST)
    assert f['values']['days'][0]['planning_base']==8
    assert f['values']['complete_days_used']==6
    s=runtime.forecast({**FORECAST,'planning_policy':'additive_stress'})
    assert s['receipt_id']!=f['receipt_id']
    assert s['values']['days'][0]['planning_base']>8
    r=runtime.inventory({'forecast_receipt_id':f['receipt_id'],'demand_scenario':'base','buffer_fraction':.25,'elapsed_exposure':.5})
    assert r['values']['stock']==0 and r['values']['projection']['unmet_demand']>0
    assert r['values']['proposed_target']==14
    assert digest(snapshot.tables)==before
    with pytest.raises(ValueError):runtime.inventory({'forecast_receipt_id':'invented','demand_scenario':'base','buffer_fraction':0})

def test_poisson_fallback_and_bounds(runtime):
    f=runtime.forecast({**FORECAST,'method':'poisson'})
    assert f['values']['requested_method_status']=='insufficient_history'
    assert f['values']['selected_method']=='mean'
    with pytest.raises(ValueError):runtime.forecast({**FORECAST,'horizon_days':999})
    with pytest.raises(ValueError):runtime.forecast({**FORECAST,'site_id':'X1'})

class ScriptedModel(Model):
    """Mock ONLY model responses. The real SDK loop executes every Python tool."""
    def __init__(self): self.turn=0; self.outputs=[]
    async def get_response(self,*args,**kwargs):
        items=kwargs.get('input',args[1] if len(args)>1 else [])
        self.outputs=[json.loads(i['output']) for i in items if isinstance(i,dict) and i.get('type')=='function_call_output']
        if self.turn==0: name,payload='describe_dataset',{}
        elif self.turn==1:
            assert self.outputs[-1]['method']=='describe_dataset'
            name,payload='query_snapshot_sql',{'request':SQL}
        elif self.turn==2:
            assert self.outputs[-1]['values']['rows'][0]['stock']==0
            name,payload='forecast_consumption',{'request':FORECAST}
        elif self.turn==3:
            f=self.outputs[-1]; assert f['method']=='forecast_consumption'
            name,payload='project_inventory',{'request':{'forecast_receipt_id':f['receipt_id'],'demand_scenario':'base','buffer_fraction':.25,'elapsed_exposure':.5}}
        else:
            r=self.outputs[-1]; assert r['values']['proposed_target']==14
            answer={'evidence_receipt_ids':[r['receipt_id']],'claims':[{'receipt_id':r['receipt_id'],'pointer':'/proposed_target','value':14}],'next_action':'request_review'}
            out=ResponseOutputMessage(id='message-final',type='message',role='assistant',status='completed',content=[ResponseOutputText(type='output_text',text=json.dumps(answer),annotations=[])])
            return ModelResponse(output=[out],usage=Usage(),response_id='response-final')
        self.turn+=1
        call=ResponseFunctionToolCall(type='function_call',name=name,arguments=json.dumps(payload),call_id=f'call-{self.turn}')
        return ModelResponse(output=[call],usage=Usage(),response_id=f'response-{self.turn}')
    async def stream_response(self,*args,**kwargs):
        raise NotImplementedError
        yield

def test_actual_sdk_tool_call_loop(snapshot,tmp_path):
    store=Store('sqlite:///'+str(tmp_path/'audit.sqlite'))
    model=ScriptedModel()
    result=asyncio.run(run_data_agent(snapshot,store,'sdk-test','Investigate H1 O-',model))
    assert [c['method'] for c in result['tool_calls']]==['describe_dataset','query_snapshot_sql','forecast_consumption','project_inventory']
    assert result['answer']['claims'][0]['value']==14
    assert len(result['model_response_ids'])==5
    assert asyncio.run(run_data_agent(snapshot,store,'sdk-test','Investigate H1 O-',model))==result
    for receipt in result['receipts']:
        assert store.get('tool_receipt',receipt['receipt_id'])==receipt
    with pytest.raises(ValueError,match='Idempotency'):
        asyncio.run(run_data_agent(snapshot,store,'sdk-test','Different question',model))

def test_claims_need_tools_and_exact_evidence(runtime):
    with pytest.raises(ValueError):checked_answer({'evidence_receipt_ids':[],'claims':[],'next_action':'request_review'},runtime)
    runtime.describe();runtime.query(SQL)
    f=runtime.forecast(FORECAST)
    r=runtime.inventory({'forecast_receipt_id':f['receipt_id'],'demand_scenario':'base','buffer_fraction':0})
    answer={'evidence_receipt_ids':[r['receipt_id']],'claims':[{'receipt_id':r['receipt_id'],'pointer':'/stock','value':0}],'next_action':'request_review'}
    checked_answer(answer,runtime)
    answer['claims'][0]['value']=10
    with pytest.raises(ValueError,match='disagrees'):checked_answer(answer,runtime)

def test_failed_model_does_not_persist_success(snapshot,tmp_path):
    class BrokenModel(ScriptedModel):
        async def get_response(self,*args,**kwargs):
            raise RuntimeError('Simulated provider failure')
    store=Store('sqlite:///'+str(tmp_path/'audit.sqlite'))
    with pytest.raises(RuntimeError):
        asyncio.run(run_data_agent(snapshot,store,'failure','Investigate H1',BrokenModel()))
    with pytest.raises(KeyError):store.get('data_agent','failure')

def test_tool_call_budget(runtime):
    for _ in range(32):runtime.describe()
    with pytest.raises(ValueError,match='budget'):runtime.describe()

def test_independent_snapshot_cannot_access_other_dataset(snapshot):
    from blood_assessment.data_access.snapshot import make_snapshot
    other=make_snapshot(snapshot.tables,snapshot.as_of,'kim',snapshot.source)
    a,b=DataTools(snapshot),DataTools(other)
    try:
        assert a.query(SQL)['receipt_id']!=b.query(SQL)['receipt_id']
    finally:
        a.close();b.close()

def test_data_agent_api_auth(snapshot,tmp_path,monkeypatch):
    from blood_assessment.service import Service
    from blood_assessment.contracts import Policy
    from blood_assessment.integration.api import create_app
    from fastapi.testclient import TestClient
    from blood_assessment.agent import data_agent
    service=Service(Store('sqlite:///'+str(tmp_path/'api.sqlite')))
    a=service.assess(snapshot,Policy(),'base')
    monkeypatch.setenv('ASSESSMENT_API_TOKEN','client')
    async def fake(snapshot,store,key,question):
        return {'snapshot_id':snapshot.snapshot_id,'question':question,'operational_writes':False}
    monkeypatch.setattr(data_agent,'run_data_agent',fake)
    client=TestClient(create_app(service))
    path=f'/assessments/{a.assessment_id}/data-agent'
    payload={'idempotency_key':'q','question':'Investigate H1'}
    assert client.post(path,json=payload).status_code==401
    r=client.post(path,json=payload,headers={'Authorization':'Bearer client'})
    assert r.status_code==200 and r.json()['snapshot_id']==snapshot.snapshot_id

@pytest.mark.skipif(__import__('os').getenv('RUN_LIVE_DATA_AGENT')!='1',reason='Requires locally configured replacement API key and model')
def test_live_data_agent(snapshot,tmp_path):
    store=Store('sqlite:///'+str(tmp_path/'live.sqlite'))
    result=asyncio.run(run_data_agent(snapshot,store,'live','Investigate H1 O- stock, forecast two calendar days with the mean baseline, then project base demand with a 25% buffer.'))
    assert {'query_snapshot_sql','forecast_consumption','project_inventory'}<={c['method'] for c in result['tool_calls']}
    assert result['answer']['claims']
