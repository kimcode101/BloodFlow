"""Approval-bound adapter contract. The graph solver is not yet supplied.

The demo adapter calls the repository's existing home-bank planner on a deep
copy and injects approved targets, without changing the source ledger.
"""
from copy import deepcopy
from datetime import timedelta
from blood_response import model as legacy
from blood_assessment.contracts import GROUPS
from blood_assessment.inventory.projection import usable

# Legacy planner has no demand/reserve injection seam. A local copy of its plan
# function is created with isolated globals, avoiding process-wide monkeypatching.
import types

def legacy_preview(snapshot, assessment, policy):
    day=snapshot.as_of.date()+timedelta(days=1)
    sites={s['site_id']:s for s in snapshot.tables['sites']}
    banks=[s for s in sites if sites[s]['type']=='blood_bank']
    needed={f'{s}/{b}' for s in banks for b in GROUPS}
    if set(policy.reserves)!=needed or any(type(v) is not int or v<0 for v in policy.reserves.values()):
        raise ValueError('Explicit nonnegative reserves required for every bank/group; no invented defaults')
    world=deepcopy(snapshot.tables)
    world['clock']=snapshot.as_of.isoformat()
    world['sites']=[dict(s,site_type=s['type']) for s in world['sites']]
    world['units']=[dict(u,site_id=u['storage_site']) for u in world['units']]
    world['travel_times']=[dict(r,route_status='provided_estimate' if r.get('minutes_rush') and r.get('minutes_normal') else 'unavailable') for r in world['travel_times']]
    world['planned_activity']=[dict(r,priority=(r['priority'] or '').replace('-','_')) for r in world['planned_activity'] if r.get('blood_type') and r.get('units_expected')]
    world['scenario']={'known_planning_start':day.isoformat(),'known_planning_end':day.isoformat(),'blood_types':GROUPS,'transfer_safety_reserve_days':0,'critical_days_of_supply':3,'low_days_of_supply':6,'demand_rule':'approved order-up-to targets, stock net of remaining-today scenario'}
    targets={(r.site_id,r.blood_type):r.target for r in assessment.proposed_requirement_updates}
    original_available=legacy.available_units
    def eligible(w,site,blood,on_date):
        stock=original_available(w,site,blood,on_date)
        if sites[site]['type']=='blood_bank':
            reserve=policy.reserves[f'{site}/{blood}']
            return stock[:max(0,len(stock)-reserve)]
        # Reserve projected remaining-day consumption locally, without executing it.
        row=next(r for r in assessment.findings if r['site_id']==site and r['blood_type']==blood)
        from math import ceil
        return stock[ceil(row['remaining_today'] or 0):]
    context=dict(legacy.plan.__globals__,baselines=lambda w:targets,available_units=eligible)
    isolated=types.FunctionType(legacy.plan.__code__,context,legacy.plan.__name__,legacy.plan.__defaults__,legacy.plan.__closure__)
    result=isolated(world)
    result.update(adapter='existing_home_bank_planner_demo_v1',graph_optimizer_status='not_implemented_by_user_yet',snapshot_id=snapshot.snapshot_id,assessment_id=assessment.assessment_id,protected_reserves=policy.reserves,status='hypothetical_only',distance_semantics='Provided distance is road-factor estimate, not aerial distance')
    validate_proposals(snapshot,result,policy,day)
    return result

def validate_proposals(snapshot,result,policy,day):
    units={u['unit_id']:u for u in snapshot.tables['units']}; seen=set(); sent={}
    for p in result['transfer_proposals']:
        if type(p['units']) is not int or p['units'] != len(p['unit_ids']): raise ValueError('Whole-unit quantity mismatch')
        for uid in p['unit_ids']:
            u=units.get(uid)
            if uid in seen or not u or u['status']!='available' or u['blood_type']!=p['blood_type'] or u['storage_site']!=p['from_site_id'] or u['expiry_date']<=day.isoformat(): raise ValueError('Ineligible or duplicate allocated unit')
            seen.add(uid)
        key=(p['from_site_id'],p['blood_type']); sent[key]=sent.get(key,0)+p['units']
    for (site,blood),qty in sent.items():
        if len(usable(snapshot,site,blood,day))-qty < policy.reserves[f'{site}/{blood}']: raise ValueError('Protected reserve violated')
