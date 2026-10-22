"""Loopback-only demo dashboard. Audit writes never touch source stock/history."""
import argparse
import os
import re
import secrets
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware
from blood_assessment.contracts import GROUPS, Policy, Snapshot
from blood_assessment.data_access.snapshot import from_csv
from blood_assessment.integration.store import Store
from blood_assessment.service import Service
from blood_assessment.demo import AS_OF

ROOT = Path(__file__).resolve().parents[1]

class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    assessment_id: str
    confirmed: Literal[True]

class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['demand_surge','donation','mixed'] = 'demand_surge'
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    planning: Literal['floor','additive_stress'] = 'floor'

class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    assessment_id: str
    question: str = Field(min_length=1, max_length=2000)
    live: bool = False


def explain(stored, plan, question):
    """Deterministic retrieval, deliberately not represented as model reasoning."""
    a, policy = stored['assessment'], stored['policy']
    q = question.lower()
    refs = [f"assessment/{a['assessment_id']}"]
    if any(word in q for word in ('reserve', 'protect')):
        answer = 'The demo protects two of the freshest eligible units per bank and blood group. Protected unit IDs are excluded before solving. This is a demo policy, not a verified operational reserve.'
        if plan:
            answer += f" This run protects {sum(len(ids) for ids in plan['inputs']['protected_reserve_unit_ids'].values())} units."
            refs.append(f"optimizer_run/{plan['optimizer_run_id']}/inputs/protected_reserve_unit_ids")
    elif any(word in q for word in ('stress', 'scenario')):
        answer = 'Floor baseline takes the larger of forecast consumption and known scheduled demand for each day. Additive stress adds them together. Both apply the approved buffer. Select the stress scenario and approve its separate run to see its calculated shortages; it is a planning assumption, not a prediction that an event will occur.'
    elif any(word in q for word in ('optimiz', 'decision', 'why this', 'distance', 'objective')):
        answer = 'The solver first minimizes priority-weighted unmet demand, then earlier unmet demand, then road distance per unit, then expiry rank. Each stage preserves the earlier objective. It enforces eligible routes, exact blood group, expiry dates, stock limits and protected reserves. These are proposed allocations; no shipment is executed.'
        if plan:
            answer += f" Saved solver status: {plan['solver_status']}."
            refs.append(f"optimizer_run/{plan['optimizer_run_id']}/stages")
    else:
        site_match = re.search(r'\bh[1-4]\b', q)
        site = site_match.group().upper() if site_match else 'H1'
        normalized = q.replace('−','-').replace('–','-').replace('negative','-').replace('positive','+')
        group_match = re.search(r'\b(ab|a|b|o)\s*([+-])', normalized)
        group = (group_match[1]+group_match[2]).upper() if group_match else 'O-'
        finding = next(x for x in a['findings'] if x['site_id']==site and x['blood_type']==group)
        requirement = next(x for x in a['proposed_requirement_updates'] if x['site_id']==site and x['blood_type']==group)
        c = requirement['components']
        answer = f"{site} {group}: the snapshot has {finding['stock']} usable units. The estimated daily consumption is {finding['daily_rate']:.3f} units. The {policy['target_days']}-day target is {finding['target']} units, including a {policy['buffer']:.0%} buffer under the {policy['planning']} policy. Known scheduled demand in that horizon is {c['known_scheduled']} units."
        if plan:
            rows = [r for r in plan['demand_results'] if r['site_id']==site and r['blood_type']==group]
            answer += f" The approved plan covers {sum(r['met'] for r in rows)} units and leaves {sum(r['unmet'] for r in rows)} unmet."
            refs.append(f"optimizer_run/{plan['optimizer_run_id']}/demand_results")
        else:
            answer += ' No allocation has been approved for this scenario yet.'
        answer += ' Forecasts use short synthetic history and are provisional.'
        refs.append(finding['evidence_ref'])
        if not any(word in q for word in ('h1','h2','h3','h4','stock','need','forecast','unit','blood')):
            answer = 'Offline evidence mode supports hospital/group stock, forecasts, reserves, scenarios and optimization objectives. Here is the default H1 O- evidence; enable a configured live model for broader investigation.\n\n' + answer
    return {'answer':answer, 'evidence_refs':refs, 'mode':'offline evidence', 'tool_calls':['read_saved_assessment'] + (['read_saved_optimization'] if plan else [])}


def create_dashboard(store=None, dist=None):
    folder = ROOT/'runs/dashboard'
    if store is None:
        folder.mkdir(parents=True, exist_ok=True)
        store = Store('sqlite:///'+str(folder/'audit.sqlite'))
    svc = Service(store)
    snapshot = from_csv(ROOT/'data/raw/team_bundle', AS_OF)
    assessments = {}
    for scenario in ('floor','additive_stress'):
        policy = Policy(planning=scenario, exposure_elapsed=.5, reserves={f'{b}/{g}':2 for b in ('B1','B2') for g in GROUPS})
        a = svc.assess(snapshot,policy,'dashboard-v1-'+scenario)
        assessments[scenario] = a.assessment_id
    allowed_ids = set(assessments.values())
    session = secrets.token_urlsafe(32)
    app = FastAPI(title='BloodFlow local dashboard', docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost','127.0.0.1','testserver'])
    dist = Path(dist or ROOT/'frontend/dist')

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.url.path.startswith('/ui/'):
            if not secrets.compare_digest(request.cookies.get('bloodflow_session',''),session):
                return JSONResponse({'detail':'Open the local dashboard first.'},status_code=401)
            if request.method != 'GET' and request.headers.get('origin') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'Same-origin request required.'},status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    def stored_for(identity):
        if identity not in allowed_ids:
            try: store.get('dashboard_simulation',identity)
            except KeyError: raise HTTPException(404,'Unknown dashboard assessment') from None
        return store.get('assessment',identity)

    def plan_for(identity):
        try: return store.get('dashboard_plan',identity)['plan']
        except KeyError: return None

    @app.get('/')
    def index():
        if not (dist/'index.html').exists(): raise HTTPException(503,'Build frontend first: cd frontend && npm ci && npm run build')
        response = FileResponse(dist/'index.html')
        response.set_cookie('bloodflow_session',session,httponly=True,samesite='strict')
        return response

    def payload(identity):
        stored = stored_for(identity)
        active_snapshot = Snapshot.model_validate(store.get('snapshot',stored['assessment']['snapshot_id']))
        try: simulation = store.get('dashboard_simulation',identity)
        except KeyError: simulation = None
        return {**stored,'plan':plan_for(identity),'sites':active_snapshot.tables['sites'],
                'live_available':bool(os.getenv('OPENAI_API_KEY') and os.getenv('OPENAI_MODEL')),
                'simulation':simulation,
                'source':'Generated synthetic test input' if simulation else 'Bundled synthetic CSV; no live database connection', 'as_of':AS_OF}

    @app.get('/ui/state')
    def state(scenario: Literal['floor','additive_stress']='floor', assessment_id: str | None=None):
        return payload(assessment_id or assessments[scenario])

    @app.post('/ui/simulate')
    def simulate(request: SimulationRequest):
        from blood_assessment.synthetic import generate
        seed = request.seed if request.seed is not None else secrets.randbelow(2147483648)
        generated, metadata = generate(snapshot,seed,request.kind)
        policy = Policy(planning=request.planning,exposure_elapsed=.5,
                        reserves={f'{b}/{g}':2 for b in ('B1','B2') for g in GROUPS})
        identity = f'simulation-v1-{seed}-{request.kind}-{request.planning}'
        assessment = svc.assess(generated,policy,identity)
        store.put('dashboard_simulation',assessment.assessment_id,metadata,metadata)
        return payload(assessment.assessment_id)

    @app.post('/ui/optimize')
    def optimize(action: Action):
        stored_for(action.assessment_id)
        cached = plan_for(action.assessment_id)
        if cached: return cached
        approval = svc.approve(action.assessment_id,'local-dashboard-demo-reviewer','approved','dashboard-approval-'+action.assessment_id)
        plan = svc.optimize(action.assessment_id,approval['approval_id'],'dashboard-plan-'+action.assessment_id)
        return store.put('dashboard_plan',action.assessment_id,{'assessment_id':action.assessment_id},{'plan':plan})['plan']

    @app.post('/ui/chat')
    async def chat(question: Question):
        stored = stored_for(question.assessment_id)
        result = explain(stored,plan_for(question.assessment_id),question.question)
        if question.live:
            if not (os.getenv('OPENAI_API_KEY') and os.getenv('OPENAI_MODEL')):
                raise HTTPException(409,'Configure OPENAI_API_KEY and OPENAI_MODEL on the server to use live investigation.')
            from blood_assessment.agent.data_agent import run_data_agent
            try:
                active_snapshot = Snapshot.model_validate(store.get('snapshot',stored['assessment']['snapshot_id']))
                analysis = await run_data_agent(active_snapshot,store,str(uuid4()),question.question)
            except Exception:
                raise HTTPException(502,'Live analysis failed. Check local server configuration; no approval or stock change occurred.') from None
            result['mode']='live data investigation + saved-plan evidence'
            result['analysis']=analysis
            result['tool_calls']=analysis['tool_calls']
        key = str(uuid4())
        result['chat_id']=key
        store.put('dashboard_chat',key,question.model_dump(),result)
        return result

    if (dist/'assets').exists(): app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(create_dashboard(), host='127.0.0.1', port=args.port)

if __name__ == '__main__': main()
