"""Run executable tools offline, or let a configured OpenAI model select calls."""
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
from blood_assessment.agent.data_agent import run_data_agent
from blood_assessment.agent.data_tools import DataTools
from blood_assessment.data_access.snapshot import from_csv,from_postgres
from blood_assessment.integration.store import Store

QUESTION='Investigate H1 O- stock and planned demand, forecast the next two calendar days, and project shortages requiring review.'

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--offline',action='store_true',help='Execute a scripted sequence of real tools, without an LLM')
    p.add_argument('--postgresql',action='store_true')
    p.add_argument('--prompt-key',action='store_true',help='Read API key with a hidden local terminal prompt; never save it')
    p.add_argument('--model',default=os.getenv('OPENAI_MODEL'))
    p.add_argument('--question',default=QUESTION)
    p.add_argument('--as-of',default='2026-10-22T12:00:00+02:00')
    p.add_argument('--output',default='runs/data-agent')
    p.add_argument('--key',default='data-investigation-v1',help='Audit idempotency key, not an API key')
    args=p.parse_args()
    if args.prompt_key:
        os.environ['OPENAI_API_KEY']=getpass.getpass('OpenAI API key (not saved): ')
    if not args.offline and (not args.model or not os.getenv('OPENAI_API_KEY')):
        p.error('Live mode requires --model/OPENAI_MODEL and OPENAI_API_KEY or --prompt-key')
    schema=os.getenv('DATA_SCHEMA','public')
    if args.postgresql:
        s=from_postgres(os.environ['DATABASE_URL'],args.as_of,schema)
    else:
        if schema!='public': p.error('Bundled fixture is public only; use --postgresql for kim')
        s=from_csv(Path(__file__).resolve().parents[1]/'data/raw/team_bundle',args.as_of)
    folder=Path(args.output);folder.mkdir(parents=True,exist_ok=True)
    store=Store('sqlite:///'+str((folder/'audit.sqlite').resolve()))
    if args.offline:
        rt=DataTools(s,store)
        try:
            rt.describe()
            rt.query({'sql':'SELECT COUNT(*) AS stock FROM units WHERE storage_site=? AND blood_type=? AND status=? AND expiry_date>?','parameters':['H1','O-','available',s.as_of.date().isoformat()],'max_rows':10})
            rt.query({'sql':'SELECT activity_id, procedure, units_expected FROM planned_activity WHERE site_id=? AND blood_type=? AND date=?','parameters':['H1','O-','2026-10-23'],'max_rows':20})
            forecast=rt.forecast({'site_id':'H1','blood_type':'O-','horizon_days':2,'method':'mean','trailing_window':7,'smoothing_alpha':.4,'planning_policy':'floor'})
            rt.inventory({'forecast_receipt_id':forecast['receipt_id'],'demand_scenario':'base','buffer_fraction':.25,'elapsed_exposure':.5})
            rt.backtest()
            report={'mode':'offline scripted real-tool execution; no model reasoning','snapshot_id':s.snapshot_id,'tool_calls':rt.calls,'receipts':list(rt.receipts.values()),'operational_writes':False}
            store.put('data_demo',args.key,{'snapshot_id':s.snapshot_id,'version':'data-tools-v1'},report)
        finally: rt.close()
    else:
        report=asyncio.run(run_data_agent(s,store,args.key,args.question,args.model))
        report['mode']='live Agents SDK model-selected tool calls'
    path=folder/'report.json';path.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False))
    print(json.dumps({'report':str(path),'mode':report['mode'],'tool_calls':len(report['tool_calls'])}))

if __name__=='__main__': main()
