"""Real computations performed at tool-call time, with immutable output receipts."""
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Literal
from pydantic import Field
from agents import function_tool
from blood_assessment.contracts import Contract, Blood, Policy
from blood_assessment.data_access.query import SnapshotSQL
from blood_assessment.data_access.snapshot import digest
from blood_assessment.forecasting.models import panel, baseline, poisson, compare
from blood_assessment.inventory.projection import usable, project, expiry_exposure, target

Hospital = Literal['H1','H2','H3','H4']
Method = Literal['last','mean','ewm','poisson']

class ForecastRequest(Contract):
    site_id: Hospital
    blood_type: Blood
    horizon_days: int = Field(ge=1,le=14)
    method: Method
    trailing_window: int = Field(ge=1,le=30)
    smoothing_alpha: float = Field(gt=0,le=1)
    planning_policy: Literal['floor','additive_stress']

class ProjectionRequest(Contract):
    forecast_receipt_id: str
    demand_scenario: Literal['low','base','high']
    buffer_fraction: float = Field(ge=0,le=3)
    elapsed_exposure: float | None = Field(default=None,gt=0,lt=1)

class SQLRequest(Contract):
    sql: str = Field(min_length=1,max_length=8000)
    parameters: list[str | int | float | None] = Field(max_length=50)
    max_rows: int = Field(ge=1,le=200)

class DataTools:
    def __init__(self,snapshot,store=None):
        self.sql=SnapshotSQL(snapshot)
        self.snapshot=self.sql.snapshot
        self.quality=self.sql.quality
        self.store=store
        self.receipts={}
        self.calls=[]
        self.attempts=0
        if store:
            payload=self.snapshot.model_dump(mode='json')
            store.put('snapshot',self.snapshot.snapshot_id,payload,payload)

    def check_budget(self):
        self.attempts+=1
        if self.attempts>32:
            raise ValueError('Investigation tool-call budget exhausted')

    def emit(self,method,parameters,values,source_refs,assumptions):
        payload={'snapshot_id':self.snapshot.snapshot_id,'dataset_schema':self.snapshot.dataset_schema,'as_of':self.snapshot.as_of.isoformat(),'tool_version':'data-tools-v1','method':method,'parameters':parameters,'values':values,'source_refs':source_refs,'warnings':self.quality['warnings'],'assumptions':assumptions}
        if len(json.dumps(payload,allow_nan=False).encode())>96_000:
            raise ValueError('Tool output exceeds byte budget; narrow the query')
        rid=digest(payload)
        payload={'receipt_id':rid,**payload}
        if self.store: payload=self.store.put('tool_receipt',rid,payload,payload)
        self.receipts[rid]=payload
        self.calls.append({'receipt_id':rid,'method':method,'parameters':parameters})
        return payload

    def describe(self):
        self.check_budget()
        return self.emit('describe_dataset',{}, {'schema':self.sql.schema(),'validation':self.quality},[self.snapshot.snapshot_id],['SQL numbers are exploratory; forecast training uses validated complete-day labels.'])

    def query(self,request):
        self.check_budget()
        request=SQLRequest.model_validate(request)
        values=self.sql.execute(request.sql,request.parameters,request.max_rows)
        return self.emit('query_snapshot_sql',request.model_dump(),values,[self.snapshot.snapshot_id],['Query is scoped to this immutable snapshot; no other schema is available.','Aggregates cite the snapshot and exact query; returned source IDs can be used for row-level evidence.','Do not add used-unit counts to daily_usage; those are the same consumption.'])

    def forecast(self,request):
        self.check_budget()
        request=ForecastRequest.model_validate(request)
        policy=Policy(window=request.trailing_window,alpha=request.smoothing_alpha,planning=request.planning_policy)
        df=panel(self.snapshot,self.quality)
        keys=[(request.site_id,request.blood_type)]
        method=request.method
        status='eligible'
        if method=='poisson' and df.date.nunique()<policy.min_ml_days:
            method='mean'; status='insufficient_history'
        try:
            rate=float(poisson(df,keys)[0] if method=='poisson' else baseline(df,keys,method,policy)[0])
        except (ValueError,FloatingPointError):
            method='mean'; status='fit_failed'; rate=float(baseline(df,keys,method,policy)[0])
        zone=ZoneInfo('Europe/Paris'); today=self.snapshot.as_of.date()
        rows=[]; refs=[]; unresolved=[]
        for n in range(1,request.horizon_days+1):
            day=today+timedelta(days=n)
            plans=[r for r in self.snapshot.tables['planned_activity'] if r['site_id']==request.site_id and r['date']==day.isoformat() and (r['blood_type']==request.blood_type or not r['blood_type'])]
            known=sum(int(r['units_expected']) for r in plans if r['blood_type']==request.blood_type and r['units_expected'])
            unresolved.extend('planned_activity/'+r['activity_id'] for r in plans if not r['blood_type'] or not r['units_expected'])
            refs.extend('planned_activity/'+r['activity_id'] for r in plans)
            planned=lambda x:max(x,known) if request.planning_policy=='floor' else x+known
            rows.append({'date':day.isoformat(),'forecast_interval':[datetime.combine(day,time(),zone).isoformat(),datetime.combine(day+timedelta(days=1),time(),zone).isoformat()],'expected_consumption':rate,'known_scheduled_units':known,'planning_low':planned(.5*rate),'planning_base':planned(rate),'planning_high':planned(1.5*rate)})
        refs.extend(f"daily_usage/{r['date']}/{r['site_id']}/{r['blood_type']}" for r in self.snapshot.tables['daily_usage'] if r['date'] in set(df.date) and (method=='poisson' or r['blood_type']==request.blood_type))
        values={'site_id':request.site_id,'blood_type':request.blood_type,'selected_method':method,'requested_method_status':status,'complete_days_used':int(df.date.nunique()),'training_cutoff':max(df.date),'daily_rate':rate,'days':rows,'unresolved_planned':unresolved,'candidate_selection':'Agent-selected scenario; not automatically the validated preferred model.'}
        return self.emit('forecast_consumption',request.model_dump(),values,[self.snapshot.snapshot_id]+refs,['Partial days excluded; sparse zeros require ledger reconciliation.','Sparse series shrink toward pooled group mean with two pseudo-days.','Daily rate is held constant across horizon; scenarios 0.5/1/1.5 are uncalibrated.','Floor policy may understate additional unscheduled demand; additive policy is stress only.'])

    def backtest(self):
        self.check_budget()
        values=compare(panel(self.snapshot,self.quality),Policy())
        return self.emit('backtest_models',Policy().model_dump(),values,[self.snapshot.snapshot_id],['Whole dates held out, one-day horizons only; short-history selection is provisional.'])

    def inventory(self,request):
        self.check_budget()
        request=ProjectionRequest.model_validate(request)
        receipt=self.receipts.get(request.forecast_receipt_id)
        if not receipt or receipt['method']!='forecast_consumption':
            raise ValueError('Use a forecast receipt returned during this investigation')
        f=receipt['values']; site,blood=f['site_id'],f['blood_type']
        today=self.snapshot.as_of.date()
        stock=usable(self.snapshot,site,blood,today)
        demands=[(datetime.fromisoformat(r['date']).date(),r['planning_'+request.demand_scenario]) for r in f['days']]
        observed=sum(int(r['units_used']) for r in self.snapshot.tables['daily_usage'] if r['date']==today.isoformat() and r['site_id']==site and r['blood_type']==blood)
        remaining=None
        if request.elapsed_exposure is not None:
            remaining=observed*(1-request.elapsed_exposure)/request.elapsed_exposure
            demands.insert(0,(today,remaining))
        qty,parts=target([v for d,v in demands if d>today],request.buffer_fraction)
        values={'site_id':site,'blood_type':blood,'stock':len(stock),'daily_rate':f['daily_rate'],'rate_based_days_of_supply':len(stock)/f['daily_rate'] if f['daily_rate']>0 else None,'expiry_exposure':expiry_exposure(stock,today),'observed_today':observed,'remaining_today':remaining,'projection':project(stock,demands),'proposed_target':qty,'target_components':parts,'requires_review':True}
        refs=[request.forecast_receipt_id]+[f"units/{u['unit_id']}" for u in stock]
        refs.extend(f"daily_usage/{r['date']}/{site}/{blood}" for r in self.snapshot.tables['daily_usage'] if r['date']==today.isoformat() and r['site_id']==site and r['blood_type']==blood)
        return self.emit('project_inventory',request.model_dump(),values,refs,['Exclusive expiry date; FEFO expected fractional consumption.','No assumed donations, future transfers, or clinical substitution.','Remaining-day scenario uses observed*(1-exposure)/exposure; unknown when omitted.','Targets cover next calendar days, exclude remaining today, and require a separate approval.'])

    def sdk_tools(self):
        @function_tool
        def describe_dataset() -> str:
            """Read SQL schema, available columns, validation, and query limits first."""
            return json.dumps(self.describe(),allow_nan=False)

        @function_tool
        def query_snapshot_sql(request: SQLRequest) -> str:
            """Execute bounded read-only SQLite SELECT with positional parameters on the validated snapshot."""
            return json.dumps(self.query(request),allow_nan=False)

        @function_tool
        def forecast_consumption(request: ForecastRequest) -> str:
            """Calculate a forecast now, choosing hospital/group, model and horizon. Returns a receipt for projection."""
            return json.dumps(self.forecast(request),allow_nan=False)

        @function_tool
        def backtest_models() -> str:
            """Run the mathematical expanding-date model comparison now; no random row splits."""
            return json.dumps(self.backtest(),allow_nan=False)

        @function_tool
        def project_inventory(request: ProjectionRequest) -> str:
            """Calculate FEFO shortages, expiry, coverage and proposed targets from a forecast receipt."""
            return json.dumps(self.inventory(request),allow_nan=False)

        return [describe_dataset,query_snapshot_sql,forecast_consumption,backtest_models,project_inventory]

    def close(self):
        self.sql.close()
