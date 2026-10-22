import os
import secrets
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import Field, AwareDatetime
from blood_assessment.contracts import Contract, Policy, Schema
from blood_assessment.data_access.snapshot import from_csv, from_postgres
from blood_assessment.integration.store import Store
from blood_assessment.service import Service
from blood_assessment.agent.assessment import run_agent

class AssessRequest(Contract):
    as_of: AwareDatetime
    dataset_schema: Schema = Field(default_factory=lambda: os.getenv('DATA_SCHEMA','public'))
    source: Literal['csv','postgresql'] = 'csv'
    policy: Policy = Field(default_factory=Policy)
    idempotency_key: str = Field(min_length=1,max_length=100)

class ApprovalRequest(Contract):
    decision: Literal['approved','rejected']
    idempotency_key: str = Field(min_length=1,max_length=100)

class OptimizeRequest(Contract):
    approval_id: str
    idempotency_key: str = Field(min_length=1,max_length=100)

class DataAgentRequest(Contract):
    idempotency_key: str = Field(min_length=1,max_length=100)
    question: str = Field(min_length=1,max_length=4000)

class AgentRequest(Contract):
    idempotency_key: str = Field(min_length=1,max_length=100)

def create_app(service=None):
    app=FastAPI(title='BloodFlow assessment',version='1.0')
    if service is None:
        Path('runs').mkdir(exist_ok=True)
        service=Service(Store(os.getenv('ASSESSMENT_DATABASE_URL','sqlite:///runs/assessment-audit.sqlite')))
    def authenticated(authorization: str = Header(default='')):
        token=os.getenv('ASSESSMENT_API_TOKEN')
        if not token: raise HTTPException(503,'Configure ASSESSMENT_API_TOKEN')
        if not secrets.compare_digest(authorization,'Bearer '+token): raise HTTPException(401,'Invalid API token')
    def reviewer(authorization: str = Header(default='')):
        token=os.getenv('ASSESSMENT_REVIEW_TOKEN'); identity=os.getenv('ASSESSMENT_REVIEWER')
        if not token or not identity: raise HTTPException(503,'Configure reviewer token and identity')
        if not secrets.compare_digest(authorization,'Bearer '+token): raise HTTPException(403,'Reviewer credentials required')
        return identity
    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422,content={'detail':str(exc)})
    @app.exception_handler(KeyError)
    async def missing(request,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404,content={'detail':'Audit record not found'})
    @app.get('/health')
    def health(): return {'status':'ok','operational_writes':False}
    @app.post('/assessments',dependencies=[Depends(authenticated)])
    def assess(body:AssessRequest):
        if body.source=='postgresql':
            url=os.environ.get('DATABASE_URL')
            if not url: raise HTTPException(503,'DATABASE_URL not configured')
            s=from_postgres(url,body.as_of,body.dataset_schema)
        else:
            if body.dataset_schema != 'public': raise ValueError('Bundled CSV is the public fixture; use PostgreSQL for kim')
            folder=Path(__file__).resolve().parents[2]/'data'/'raw'/'team_bundle'
            s=from_csv(folder,body.as_of,body.dataset_schema)
        return service.assess(s,body.policy,body.idempotency_key)
    @app.get('/assessments/{assessment_id}',dependencies=[Depends(authenticated)])
    def get(assessment_id:str): return service.store.get('assessment',assessment_id)
    @app.post('/assessments/{assessment_id}/approvals')
    def approve(assessment_id:str,body:ApprovalRequest,identity:str=Depends(reviewer)):
        return service.approve(assessment_id,identity,body.decision,body.idempotency_key)
    @app.post('/assessments/{assessment_id}/proposals',dependencies=[Depends(authenticated)])
    def propose(assessment_id:str,body:OptimizeRequest): return service.optimize(assessment_id,body.approval_id,body.idempotency_key)
    @app.get('/optimization/{run_id}',dependencies=[Depends(authenticated)])
    def optimization(run_id:str): return service.store.get('optimizer_run',run_id)
    @app.get('/optimization/{run_id}/graph',dependencies=[Depends(authenticated)])
    def graph(run_id:str):
        result=service.store.get('optimizer_run',run_id)
        if 'graph' not in result: raise HTTPException(404,'This optimizer did not return graph data')
        return result['graph']
    @app.post('/assessments/{assessment_id}/agent',dependencies=[Depends(authenticated)])
    async def agent(assessment_id:str,body:AgentRequest):
        try: return await run_agent(service,assessment_id,body.idempotency_key)
        except (ValueError,KeyError): raise
        except Exception: raise HTTPException(502,'Agent failed; deterministic assessment and operational state unchanged')
    @app.post('/assessments/{assessment_id}/data-agent',dependencies=[Depends(authenticated)])
    async def data_agent(assessment_id:str,body:DataAgentRequest):
        from blood_assessment.agent.data_agent import run_data_agent
        from blood_assessment.contracts import Snapshot
        stored=service.store.get('assessment',assessment_id)
        snapshot=Snapshot.model_validate(service.store.get('snapshot',stored['assessment']['snapshot_id']))
        try:
            return await run_data_agent(snapshot,service.store,body.idempotency_key,body.question)
        except (ValueError,KeyError): raise
        except Exception: raise HTTPException(502,'Data agent failed; operational state unchanged')
    return app
