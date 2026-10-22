from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import importlib.metadata
from blood_assessment.contracts import Forecast, GROUPS
from blood_assessment.data_access.snapshot import digest
from blood_assessment.forecasting.models import panel, compare, baseline, poisson

ASSUMPTIONS=['Only complete dates train models; partial usage is separate.', 'Sparse series use two pooled group pseudo-days.', 'Low/base/high = 0.5/1/1.5 times mean; uncalibrated scenarios, not confidence bounds.', 'Floor planning may understate additional unscheduled demand.', 'No weekly seasonality or learned future activity effect.', 'Daily rate is held constant over the horizon; ML lag/trailing features are frozen at training cutoff.']

def run(snapshot,quality,policy):
    df=panel(snapshot,quality)
    comparison=compare(df,policy)
    sites=sorted(r['site_id'] for r in snapshot.tables['sites'] if r['type']=='hospital')
    keys=[(s,b) for s in sites for b in GROUPS]
    method=comparison['selected']
    try: values=poisson(df,keys) if method=='poisson' else baseline(df,keys,method,policy)
    except (ValueError,FloatingPointError):
        method='mean'; comparison.update(selected='mean',ml_status='fit_failed')
        values=baseline(df,keys,method,policy)
    zone=ZoneInfo('Europe/Paris'); today=snapshot.as_of.astimezone(zone).date()
    records=[]; remaining=[]
    for (site,blood),value in zip(keys,values):
        observed=sum(int(r['units_used']) for r in snapshot.tables['daily_usage'] if r['site_id']==site and r['blood_type']==blood and r['date']==today.isoformat())
        remaining.append({'site_id':site,'blood_type':blood,'observed_today':observed,'expected_remaining':observed*(1-policy.exposure_elapsed)/policy.exposure_elapsed if policy.exposure_elapsed is not None else None, 'interval':[snapshot.as_of.isoformat(),datetime.combine(today+timedelta(days=1),time(),zone).isoformat()], 'assumption':'Configured exposure fraction; not an observed full-day label' if policy.exposure_elapsed else 'No intraday assumption supplied'})
        history_refs=[f"daily_usage/{r['date']}/{r['site_id']}/{r['blood_type']}" for r in snapshot.tables['daily_usage'] if r['date'] in set(df.date) and (r['blood_type']==blood or method=='poisson')] + [f'{snapshot.snapshot_id}/validation/sparse_reconciliation']
        for n in range(1,15):
            day=today+timedelta(days=n)
            plans=[r for r in snapshot.tables['planned_activity'] if r['site_id']==site and r['blood_type']==blood and r['date']==day.isoformat() and r['units_expected']]
            known=sum(int(r['units_expected']) for r in plans)
            requirement=max(float(value),known) if policy.planning=='floor' else float(value)+known
            records.append(Forecast(site_id=site,blood_type=blood,forecast_interval=(datetime.combine(day,time(),zone),datetime.combine(day+timedelta(days=1),time(),zone)),expected_consumption=float(value),uncertainty_range=(.5*value,1.5*value),uncertainty_method='uncalibrated_low_high_scenario',selected_method=method,training_window=(min(df.date),max(df.date)),complete_days_used=df.date.nunique(),backtest_metrics=comparison['metrics'][method],known_scheduled_units=known,planning_policy=policy.planning,proposed_requirement=requirement,assumptions=ASSUMPTIONS,source_refs=history_refs+[f"planned_activity/{r['activity_id']}" for r in plans]).model_dump(mode='json'))
    config={'policy':policy.model_dump(),'seed':42,'features':['site_id','blood_type','lag','trailing_3_prior_observations'],'poisson_alpha':1.,'versions':{p:importlib.metadata.version(p) for p in ('numpy','pandas','scikit-learn','openai-agents')},'training_cutoff':max(df.date),'model_version':'short-history-v1'}
    return {'forecast_run_id':digest([snapshot.snapshot_id,config]),'snapshot_id':snapshot.snapshot_id,'as_of':snapshot.as_of.isoformat(),'records':records,'remaining_today':remaining,'comparison':comparison,'configuration':config,'view':'Days 1-7 consumption forecasts; days 1-14 separate planning view', 'warnings':quality['warnings']}
