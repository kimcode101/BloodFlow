from datetime import date, timedelta, datetime, timezone
from math import ceil
from blood_assessment.contracts import AssessmentRun, Requirement, Policy, Snapshot, AgentReview
from blood_assessment.data_access.snapshot import digest
from blood_assessment.data_access.validation import validate
from blood_assessment.forecasting.run import run
from blood_assessment.inventory.projection import usable, project, expiry_exposure, target
from blood_assessment.policies.risk import priority

def build(snapshot,policy):
    quality=validate(snapshot)
    forecasts=run(snapshot,quality,policy)
    findings=[]; requirements=[]; priorities=[]
    today=snapshot.as_of.date()
    for remainder in forecasts['remaining_today']:
        site,blood=remainder['site_id'],remainder['blood_type']
        rows=[r for r in forecasts['records'] if r['site_id']==site and r['blood_type']==blood]
        stock=usable(snapshot,site,blood,today)
        demands=[(date.fromisoformat(r['forecast_interval'][0][:10]),r['proposed_requirement']) for r in rows]
        if remainder['expected_remaining'] is not None: demands.insert(0,(today,remainder['expected_remaining']))
        projection=project(stock,demands)
        qty,components=target([r['proposed_requirement'] for r in rows[:policy.target_days]],policy.buffer)
        components.update(horizon_days=policy.target_days,planning_policy=policy.planning,known_scheduled=sum(r['known_scheduled_units'] for r in rows[:policy.target_days]),baseline=sum(r['expected_consumption'] for r in rows[:policy.target_days]))
        cumulative=0.0
        previous=0
        dated=[]
        for row in rows[:policy.target_days]:
            cumulative+=row['proposed_requirement']
            rounded=ceil(cumulative*(1+policy.buffer))
            dated.append({'date':row['forecast_interval'][0][:10], 'units':rounded-previous,
                          'planning_requirement':row['proposed_requirement'],
                          'known_scheduled_units':row['known_scheduled_units']})
            previous=rounded
        assert previous==qty
        components['dated_requirements']=dated
        components['rounding']='differences of cumulative ceilings; sum equals approved target'
        ref=f"{forecasts['forecast_run_id']}/inventory/{site}/{blood}"
        rate=rows[0]['expected_consumption']
        exp=expiry_exposure(stock,today)
        finding={'evidence_ref':ref,'site_id':site,'blood_type':blood,'stock':len(stock),'daily_rate':rate,'days_of_supply':len(stock)/rate if rate>0 else None,'coverage_status':'rate_based' if rate>0 else 'zero_rate_no_finite_coverage','target':qty,'unmet_demand':projection['unmet_demand'],'expiry_3_days':exp['3'],'expiry_exposure':exp,'projection':projection,'remaining_today':remainder['expected_remaining'],'source_refs':[f"units/{u['unit_id']}" for u in stock]+sorted(set(x for r in rows for x in r['source_refs'])),'assumptions':['Expiry exposure is not predicted waste.','Projection has no future donations or historical-transfer arrivals.']}
        findings.append(finding)
        requirements.append(Requirement(site_id=site,blood_type=blood,target=qty,components=components,evidence_ref=ref))
        # Central versioned deterministic policy, never LLM-provided weights.
        score=priority(projection, exp['3'], policy.target_days+(remainder['expected_remaining'] is not None))
        priorities.append({'site_id':site,'blood_type':blood,'priority_score':score,'policy_version':policy.version,'evidence_ref':ref})
    assessment=AssessmentRun(assessment_id=digest([snapshot.snapshot_id,forecasts['forecast_run_id'],policy.model_dump()]),snapshot_id=snapshot.snapshot_id,dataset_schema=snapshot.dataset_schema,as_of=snapshot.as_of,forecast_run_ids=[forecasts['forecast_run_id']],model_version='short-history-v1',policy_version=policy.version,findings=findings,proposed_requirement_updates=requirements,proposed_priority_updates=priorities,unresolved_data_issues=quality['unresolved_planned']+quality['warnings']+([] if policy.exposure_elapsed else ['No remaining-today estimate; future projection conditional on unchanged stock until tomorrow.']),evidence_refs=[r['evidence_ref'] for r in findings],explanation='Deterministic assessment, pending human review. Forecast scenarios are provisional; proposed requirements do not update operational stock or confirmed demand.')
    return quality,forecasts,assessment

def validate_review(review,assessment):
    review=AgentReview.model_validate(review)
    evidence={r['evidence_ref']:r for r in assessment.findings}
    if not set(review.finding_refs)<=set(evidence): raise ValueError('Unknown finding evidence')
    for claim in review.claims:
        if claim.evidence_ref not in evidence or evidence[claim.evidence_ref][claim.field] != claim.value:
            raise ValueError('Agent numerical claim differs from immutable tool output')
    return review

class Service:
    def __init__(self,store,optimizer=None):
        self.store=store
        self.optimizer=optimizer

    def assess(self,snapshot,policy,key):
        from blood_assessment.data_access.snapshot import make_snapshot
        verified=make_snapshot(snapshot.tables,snapshot.as_of,snapshot.dataset_schema,snapshot.source)
        if verified.snapshot_id != snapshot.snapshot_id or verified.data_hash != snapshot.data_hash:
            raise ValueError('Snapshot fingerprint mismatch')
        request={'snapshot_id':snapshot.snapshot_id,'policy':policy.model_dump()}
        cached=self.store.lookup('request',key,request)
        if cached: return AssessmentRun.model_validate(cached)
        quality,forecasts,assessment=build(snapshot,policy)
        self.store.put('snapshot',snapshot.snapshot_id,snapshot.model_dump(mode='json'),snapshot.model_dump(mode='json'))
        self.store.put('forecast',forecasts['forecast_run_id'],forecasts,forecasts)
        payload={'assessment':assessment.model_dump(mode='json'),'policy':policy.model_dump(),'quality':quality}
        self.store.put('assessment',assessment.assessment_id,payload,payload)
        persisted=self.store.put('request',key,request,assessment.model_dump(mode='json'))
        return AssessmentRun.model_validate(persisted)

    def approve(self,assessment_id,reviewer,decision,key):
        self.store.get('assessment',assessment_id)
        if decision not in ('approved','rejected') or not reviewer.strip(): raise ValueError('Explicit reviewer and decision required')
        request={'assessment_id':assessment_id,'reviewer':reviewer,'decision':decision}
        payload={**request,'approval_id':digest([assessment_id,key]),'at':datetime.now(timezone.utc).isoformat()}
        payload=self.store.put('approval',key,request,payload)
        self.store.put('approval_id',payload['approval_id'],payload,payload)
        return payload

    def optimize(self,assessment_id,approval_id,key):
        stored=self.store.get('assessment',assessment_id)
        approval=self.store.get('approval_id',approval_id)
        if approval['assessment_id']!=assessment_id or approval['decision']!='approved': raise ValueError('Matching explicit approval required')
        request={'assessment_id':assessment_id,'approval_id':approval_id,'optimizer': 'dated-cp-sat-v1' if self.optimizer is None else type(self.optimizer).__qualname__}
        cached=self.store.lookup('optimizer',key,request)
        if cached: return cached
        s=Snapshot.model_validate(self.store.get('snapshot',stored['assessment']['snapshot_id']))
        assessment=AssessmentRun.model_validate(stored['assessment'])
        policy=Policy.model_validate(stored['policy'])
        if self.optimizer is None:
            from blood_assessment.optimization.adapter import graph_preview
            result=graph_preview(s,assessment,policy)
        else:
            from blood_assessment.integration.optimizer_contract import external_preview
            result=external_preview(self.optimizer,s,assessment,policy)
        result['approval_id']=approval_id
        result['optimizer_run_id']=digest([request,key])
        result=self.store.put('optimizer',key,request,result)
        self.store.put('optimizer_run',result['optimizer_run_id'],result,result)
        return result
