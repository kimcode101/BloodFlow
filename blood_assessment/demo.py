"""Reproducible offline demo; explicit fixture approval, no model/API call by default."""
import argparse
import asyncio
import json
from pathlib import Path
from blood_assessment.contracts import GROUPS, Policy
from blood_assessment.data_access.snapshot import from_csv, from_postgres, digest
from blood_assessment.data_access.validation import validate
from blood_assessment.inventory.projection import usable, expiry_exposure
from blood_assessment.integration.store import Store
from blood_assessment.service import Service
from blood_assessment.agent.assessment import run_agent

AS_OF='2026-10-22T12:00:00+02:00'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='runs/assessment-demo')
    parser.add_argument('--postgresql',action='store_true')
    parser.add_argument('--live-agent',action='store_true')
    args=parser.parse_args()
    import os
    schema=os.getenv('DATA_SCHEMA','public')
    if not args.postgresql and schema != 'public': raise ValueError('Bundled CSV is the public fixture; use PostgreSQL for kim')
    source=Path(__file__).resolve().parents[1]/'data/raw/team_bundle'
    s=from_postgres(os.environ['DATABASE_URL'],AS_OF,schema) if args.postgresql else from_csv(source,AS_OF,schema)
    before=digest(s.tables)
    folder=Path(args.output); folder.mkdir(parents=True,exist_ok=True)
    svc=Service(Store('sqlite:///'+str(folder/'audit.sqlite')))
    # Explicit DEMO policy, not inferred operational reserve data.
    policy=Policy(exposure_elapsed=.5,reserves={f'{bank}/{g}':2 for bank in ('B1','B2') for g in GROUPS})
    a=svc.assess(s,policy,'demo-base')
    decision=svc.approve(a.assessment_id,'offline-demo-reviewer','approved','demo-approval')
    proposal=svc.optimize(a.assessment_id,decision['approval_id'],'demo-proposal')
    # Change only the policy, not the snapshot or planned/historical records.
    stress=policy.model_copy(update={'planning':'additive_stress'})
    b=svc.assess(s,stress,'demo-stress')
    stress_approval=svc.approve(b.assessment_id,'offline-demo-reviewer','approved','demo-stress-approval')
    stress_proposal=svc.optimize(b.assessment_id,stress_approval['approval_id'],'demo-stress-proposal')
    facts={'source':s.source,'database_verified':args.postgresql,'totals':validate(s)['totals'],'H1_O_negative_stock':len(usable(s,'H1','O-',s.as_of.date())),'H1_tomorrow_O_negative_activities':[r for r in s.tables['planned_activity'] if r['site_id']=='H1' and r['blood_type']=='O-' and r['date']=='2026-10-23'],'H2_A_negative':[r for r in a.findings if r['site_id']=='H2' and r['blood_type']=='A-'],'banks':{bank:{'O_negative_stock':len(usable(s,bank,'O-',s.as_of.date())),'expiry_exposure':expiry_exposure(usable(s,bank,'O-',s.as_of.date()),s.as_of.date()),'source_units':[u for u in s.tables['units'] if u['storage_site']==bank and u['blood_type']=='O-' and u['status']=='available']} for bank in ('B1','B2')}}
    report={'facts':facts,'assessment':a.model_dump(mode='json'),'forecast':svc.store.get('forecast',a.forecast_run_ids[0]),'approval':decision,'proposal':proposal,'controlled_policy_update':{'assessment':b.model_dump(mode='json'),'approval':stress_approval,'proposal':stress_proposal},'agent_mode':'deterministic offline assessment; live SDK call not run','source_unchanged':before==digest(s.tables),'limitations':['Single dispatch dated CP-SAT model; no fleet or actual shipment execution.','CSV evidence is not live database verification.','Demo reserve is explicitly two units per bank/group, not operational data.']}
    if args.live_agent:
        report['agent_review']=asyncio.run(run_agent(svc,a.assessment_id,'demo-live-agent'))
        report['agent_mode']='live OpenAI Agents SDK'
    (folder/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps({'report':str(folder/'report.json'),'totals':facts['totals'],'source_unchanged':report['source_unchanged'],'proposal_count':len(proposal['transfer_proposals']),'solver_status':proposal['solver_status'],'summary':proposal['summary']},indent=2))

if __name__=='__main__': main()
