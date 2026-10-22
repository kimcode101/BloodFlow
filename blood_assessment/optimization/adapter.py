"""Convert approved dated requirements and source units into the graph problem."""
from collections import defaultdict
from datetime import date,datetime,time,timedelta,timezone
from math import ceil,isfinite
from zoneinfo import ZoneInfo
from blood_assessment.contracts import GROUPS
from blood_assessment.data_access.snapshot import digest,make_snapshot
from blood_assessment.data_access.validation import validate
from blood_assessment.inventory.projection import usable
from blood_assessment.optimization.solver import solve,ENGINE_VERSION


def prepare_problem(snapshot,assessment,policy):
    verified=make_snapshot(snapshot.tables,snapshot.as_of,snapshot.dataset_schema,snapshot.source)
    if snapshot.snapshot_id!=verified.snapshot_id or snapshot.data_hash!=verified.data_hash:
        raise ValueError('Snapshot fingerprint mismatch')
    if assessment.snapshot_id!=snapshot.snapshot_id:raise ValueError('Assessment/snapshot mismatch')
    validate(snapshot)
    today=snapshot.as_of.date(); first=today+timedelta(days=1)
    sites={r['site_id']:r for r in snapshot.tables['sites']}
    banks=sorted(k for k,v in sites.items() if v['type']=='blood_bank')
    hospitals=sorted(k for k,v in sites.items() if v['type']=='hospital')
    reserve_keys={f'{b}/{g}' for b in banks for g in GROUPS}
    if set(policy.reserves)!=reserve_keys or any(type(v) is not int or v<0 for v in policy.reserves.values()):
        raise ValueError('Explicit nonnegative reserves required for every bank/group')
    warnings=list(assessment.unresolved_data_issues)
    priorities={}
    for r in assessment.proposed_priority_updates:
        key=(r['site_id'],r['blood_type'])
        score=r['priority_score']
        if key in priorities or type(score) is not int or not 0<=score<=100:raise ValueError('Invalid group priority')
        priorities[key]=score
    demands=[]; expected={(h,g) for h in hospitals for g in GROUPS}; seen=set()
    for req in assessment.proposed_requirement_updates:
        key=(req.site_id,req.blood_type)
        if key not in expected or key in seen:raise ValueError('Duplicate or unknown requirement')
        seen.add(key)
        rows=req.components.get('dated_requirements')
        if not rows:raise ValueError('Reassess and approve dated requirements before using the graph optimizer')
        if key not in priorities:raise ValueError('Missing approved priority')
        days=[r['date'] for r in rows]
        required_days=[(first+timedelta(days=i)).isoformat() for i in range(policy.target_days)]
        if days!=required_days:raise ValueError('Dated requirements do not match approved horizon')
        if sum(r['units'] for r in rows)!=req.target:raise ValueError('Dated requirements differ from approved target')
        for r in rows:
            if type(r['units']) is not int or not 0<=r['units']<=1_000_000:raise ValueError('Invalid dated units')
            demands.append({'site_id':req.site_id,'blood_type':req.blood_type,'date':r['date'],
                            'units':r['units'],'priority_score':priorities[key],'evidence_ref':req.evidence_ref})
    if seen!=expected:raise ValueError('Requirements must cover every hospital/group')
    protected={}; withheld=[]; reserve_shortfalls=[]; local_today=[]; eligible=[]
    for bank in banks:
        for group in GROUPS:
            stock=usable(snapshot,bank,group,first)
            reserve=policy.reserves[f'{bank}/{group}']
            count=min(len(stock),reserve)
            keep=stock[-count:] if count else []
            protected[f'{bank}/{group}']=[u['unit_id'] for u in keep]
            withheld.extend(u['unit_id'] for u in keep)
            eligible.extend(stock[:len(stock)-count])
            if len(stock)<reserve:
                reserve_shortfalls.append({'site_id':bank,'blood_type':group,'requested_reserve':reserve,'eligible_stock':len(stock),'shortfall':reserve-len(stock)})
    findings={(r['site_id'],r['blood_type']):r for r in assessment.findings}
    for h in hospitals:
        for g in GROUPS:
            stock=usable(snapshot,h,g,today)
            remaining=findings[h,g]['remaining_today']
            if remaining is None:
                used=0
            else:
                if not isfinite(remaining) or remaining<0:raise ValueError('Invalid remaining-day scenario')
                used=ceil(remaining)
            consumed=stock[:used]
            local_today.append({'site_id':h,'blood_type':g,'scenario_remaining':remaining,
                                'reserved_units':len(consumed),'unit_ids':[u['unit_id'] for u in consumed],
                                'unmet_today':max(0,used-len(consumed)) if remaining is not None else None})
            eligible.extend(u for u in stock[used:] if u['expiry_date']>first.isoformat())
    grouped=defaultdict(list)
    for unit in eligible:
        grouped[unit['storage_site'],unit['blood_type'],unit['expiry_date']].append(unit['unit_id'])
    lots=[{'site_id':s,'type':sites[s]['type'],'blood_type':g,'expiry_date':expiry,
           'expiry_rank':(date.fromisoformat(expiry)-first).days,'unit_ids':sorted(ids)}
          for (s,g,expiry),ids in sorted(grouped.items())]
    if len(eligible)>100_000:raise ValueError('Graph demo unit limit exceeded')
    deadline=datetime.combine(first,time(),ZoneInfo('Europe/Paris'))
    minutes_available=(deadline.astimezone(timezone.utc)-snapshot.as_of.astimezone(timezone.utc)).total_seconds()/60
    routes=[];blocked=[]
    records={(r['from_site_id'],r['to_site_id']):r for r in snapshot.tables['travel_times']}
    for b in banks:
        for h in hospitals:
            r=records.get((b,h));reason=None
            if not r:reason='missing_travel_link'
            elif not r.get('distance_km') or not r.get('minutes_'+policy.graph.traffic):reason='missing_route_values'
            else:
                distance=float(r['distance_km']); minutes=float(r['minutes_'+policy.graph.traffic])
                if not isfinite(distance) or not isfinite(minutes) or distance<=0 or minutes<=0:reason='invalid_route_values'
                elif minutes>minutes_available:reason='cannot_arrive_before_first_planning_day'
            if reason:
                blocked.append({'from_site_id':b,'to_site_id':h,'reason':reason})
            else:
                routes.append({'from_site_id':b,'to_site_id':h,'distance_km':distance,
                               'distance_metres':max(1,round(distance*1000)),'minutes':minutes})
    return {'version':ENGINE_VERSION,'snapshot_id':snapshot.snapshot_id,'assessment_id':assessment.assessment_id,
            'as_of':snapshot.as_of.isoformat(),'allocation_date':first.isoformat(),
            'demands':sorted(demands,key=lambda d:(d['date'],d['site_id'],d['blood_type'])),
            'lots':lots,'routes':routes,'blocked_routes':blocked,
            'protected_reserve_unit_ids':protected,'reserve_shortfalls':reserve_shortfalls,
            'remaining_today':local_today,'config':policy.graph.model_dump(),
            'warnings':warnings,'distance_semantics':'Supplied road-factor distance (1.3), not aerial Haversine.',
            'timing_assumption':'Single dispatch after snapshot; all transfers must arrive by first planning-day midnight. Daily requirement slots are planning conventions, not procedure times.',
            'reserve_assumption':'Withhold freshest eligible bank units at dispatch. No bank consumption or guaranteed reserve level after those units expire.',
            'expiry_assumption':'Units may only satisfy a requirement dated strictly before expiry_date.',
            'priority_assumption':'Approved hospital/group scores; integer weight=100+score. Earlier unmet requirements break priority-objective ties.'}


def graph_preview(snapshot,assessment,policy):
    problem=prepare_problem(snapshot,assessment,policy)
    result=solve(problem)
    result.update(adapter=ENGINE_VERSION,snapshot_id=snapshot.snapshot_id,
                  assessment_id=assessment.assessment_id,status='hypothetical_only',
                  input_hash=digest(problem),inputs=problem)
    sites=snapshot.tables['sites']
    result['graph']={'nodes':[{'id':r['site_id'],'name':r['name'],'type':r['type'],
                              'latitude':float(r['lat']) if r.get('lat') else None,
                              'longitude':float(r['lon']) if r.get('lon') else None} for r in sites],
                     'connections':problem['routes'],'blocked_connections':problem['blocked_routes'],
                     'edges':[{'source':p['from_site_id'],'target':p['to_site_id'],
                               'blood_type':p['blood_type'],'units':p['units'],
                               'distance_km':p['distance_km']} for p in result['transfer_proposals']]}
    return result
