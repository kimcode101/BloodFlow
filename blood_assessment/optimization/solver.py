"""CP-SAT adaptation of hackathon/backend/optimizer/solver.py.

Preserves exact integer, sequential lexicographic solves, one worker/seed zero,
valid incumbent fallback and explicit failure statuses. Adds expiry lots, dated
requirements, supplied routes, and per-hospital/blood-group approved priorities.
No database or mutation of operational records occurs here.
"""
from collections import defaultdict
from copy import deepcopy
from time import perf_counter
import ortools
from ortools.sat.python import cp_model

ENGINE_VERSION='dated-cp-sat-v1'


def lexicographic(model, objectives, variables, max_seconds, solver_factory=cp_model.CpSolver):
    """Only constrain the preceding objective after its optimum is proved."""
    saved=None
    stages=[]
    status_name='UNKNOWN'
    for name,objective in objectives:
        model.minimize(objective)
        solver=solver_factory()
        solver.parameters.num_search_workers=1
        solver.parameters.random_seed=0
        solver.parameters.max_time_in_seconds=max_seconds
        status=solver.solve(model)
        status_name=solver.status_name(status)
        valid=status in (cp_model.OPTIMAL,cp_model.FEASIBLE)
        value=int(solver.value(objective)) if valid else None
        stages.append({'objective':name,'status':status_name,'value':value,'optimal':status==cp_model.OPTIMAL})
        if not valid:
            return saved, stages, 'FEASIBLE_PREVIOUS_STAGE' if saved is not None else status_name
        saved={key:int(solver.value(v)) for key,v in variables.items()}
        if status!=cp_model.OPTIMAL:
            return saved,stages,'FEASIBLE'
        model.add(objective==value)
    return saved,stages,status_name


def solve(problem):
    """Internal validated problem; cohorts have identical site/group/expiry."""
    started=perf_counter()
    model=cp_model.CpModel()
    lots=problem['lots']; demands=problem['demands']; routes=problem['routes']
    edges={(r['from_site_id'],r['to_site_id']):r for r in routes}
    dates=sorted({d['date'] for d in demands})
    x={}; unmet={}; incoming=defaultdict(list); outgoing=defaultdict(list)
    for li,lot in enumerate(lots):
        for di,demand in enumerate(demands):
            if lot['blood_type']!=demand['blood_type'] or lot['expiry_date']<=demand['date']:
                continue
            if lot['type']=='hospital':
                if lot['site_id']!=demand['site_id']: continue
            elif (lot['site_id'],demand['site_id']) not in edges:
                continue
            cap=min(len(lot['unit_ids']),demand['units'])
            if not cap: continue
            var=model.new_int_var(0,cap,f'x_{li}_{di}')
            x[li,di]=var; incoming[di].append(var);outgoing[li].append(var)
    for li,lot in enumerate(lots):
        model.add(sum(outgoing[li])<=len(lot['unit_ids']))
    for di,d in enumerate(demands):
        unmet[di]=model.new_int_var(0,d['units'] if problem['config']['allow_unmet_demand'] else 0,f'u_{di}')
        model.add(sum(incoming[di])+unmet[di]==d['units'])
    priority=sum((100+d['priority_score'])*unmet[i] for i,d in enumerate(demands))
    urgency=sum((len(dates)-dates.index(d['date']))*unmet[i] for i,d in enumerate(demands))
    distance=sum(edges[lots[li]['site_id'],demands[di]['site_id']]['distance_metres']*var
                 for (li,di),var in x.items() if lots[li]['type']=='blood_bank')
    expiry=sum(lots[li]['expiry_rank']*var for (li,di),var in x.items())
    variables={('x',li,di):v for (li,di),v in x.items()}
    variables.update({('u',di):v for di,v in unmet.items()})
    values,stages,status=lexicographic(model,[('priority_weighted_unmet',priority),('earlier_demand_unmet',urgency),('transport_unit_metres',distance),('expiry_preference',expiry)],variables,problem['config']['max_seconds_per_stage'])
    result={'engine_version':ENGINE_VERSION,'solver_version':ortools.__version__,'solver_status':status,
            'stages':stages,'config':problem['config'],'transfer_proposals':[], 'assignments':[],
            'demand_results':[], 'summary':None,'solver_runtime_ms':(perf_counter()-started)*1000}
    if values is None:
        return result
    pool={i:list(lot['unit_ids']) for i,lot in enumerate(lots)}
    transfers={}; allocations=defaultdict(int); local=defaultdict(int)
    for (li,di),var in sorted(x.items(),key=lambda item:(demands[item[0][1]]['date'],item[0][0],item[0][1])):
        qty=values['x',li,di]
        if not qty: continue
        lot,d=lots[li],demands[di]
        selected=pool[li][:qty];del pool[li][:qty]
        result['assignments'].append({'source_site_id':lot['site_id'],'site_id':d['site_id'],'blood_type':d['blood_type'],'requirement_date':d['date'],'expiry_date':lot['expiry_date'],'units':qty,'unit_ids':selected})
        allocations[di]+=qty
        if lot['type']=='hospital':local[di]+=qty
        else:
            key=(lot['site_id'],d['site_id'],d['blood_type'])
            if key not in transfers:
                route=edges[key[0],key[1]]
                transfers[key]={'from_site_id':key[0],'to_site_id':key[1],'blood_type':key[2],
                                'units':0,'unit_ids':[],'allocation_date':problem['allocation_date'],
                                'distance_km':route['distance_km'],'estimated_minutes':route['minutes'],
                                'status':'hypothetical_approved_proposal'}
            transfers[key]['units']+=qty;transfers[key]['unit_ids'].extend(selected)
    result['transfer_proposals']=[transfers[k] for k in sorted(transfers)]
    for i,d in enumerate(demands):
        result['demand_results'].append({**d,'met':allocations[i],'local_units':local[i],
                                         'inbound_units':allocations[i]-local[i],'unmet':values['u',i]})
    result['summary']={'total_requirement':sum(d['units'] for d in demands),
        'total_met':sum(allocations.values()),'total_unmet':sum(values['u',i] for i in range(len(demands))),
        'total_transferred':sum(p['units'] for p in transfers.values()),
        'total_local_used':sum(local.values()),
        'weighted_unmet':sum((100+d['priority_score'])*values['u',i] for i,d in enumerate(demands))/100,
        'road_unit_km':sum(p['units']*p['distance_km'] for p in transfers.values()),
        'all_stages_optimal':len(stages)==4 and all(s['optimal'] for s in stages)}
    validate_solution(problem,result)
    return result


def validate_solution(problem,result):
    """Independent reconstruction of capacities, expiry, dates and conservation."""
    if result['summary'] is None:
        if result['transfer_proposals'] or result['assignments']: raise ValueError('Failed solve emitted allocations')
        return
    units={uid:lot for lot in problem['lots'] for uid in lot['unit_ids']}
    demands={(d['site_id'],d['blood_type'],d['date']):d for d in problem['demands']}
    routes={(r['from_site_id'],r['to_site_id']) for r in problem['routes']}
    seen=set();met=defaultdict(int);expected_transfers=defaultdict(set)
    for a in result['assignments']:
        key=(a['site_id'],a['blood_type'],a['requirement_date'])
        if key not in demands or type(a['units']) is not int or a['units']<=0 or a['units']!=len(a['unit_ids']):raise ValueError('Invalid assignment')
        for uid in a['unit_ids']:
            lot=units.get(uid)
            if uid in seen or not lot or lot['blood_type']!=a['blood_type'] or lot['site_id']!=a['source_site_id'] or lot['expiry_date']<=a['requirement_date']:
                raise ValueError('Unit reused, wrong blood group or ineligible expiry')
            seen.add(uid)
            if lot['type']=='hospital':
                if lot['site_id']!=a['site_id']:raise ValueError('Hospital transshipment prohibited')
            else:
                if (lot['site_id'],a['site_id']) not in routes:raise ValueError('Route unavailable')
                expected_transfers[lot['site_id'],a['site_id'],a['blood_type']].add(uid)
        met[key]+=a['units']
    if len(result['demand_results'])!=len(demands):raise ValueError('Missing demand results')
    seen_demands=set()
    for r in result['demand_results']:
        key=(r['site_id'],r['blood_type'],r['date'])
        if key in seen_demands or key not in demands:raise ValueError('Duplicate or unknown demand')
        seen_demands.add(key)
        if type(r['unmet']) is not int or r['unmet']<0 or met[key]+r['unmet']!=demands[key]['units'] or r['met']!=met[key]:raise ValueError('Demand conservation violated')
    actual={}; transfer_ids=[]
    for p in result['transfer_proposals']:
        key=(p['from_site_id'],p['to_site_id'],p['blood_type'])
        if key in actual or type(p['units']) is not int or p['units']!=len(p['unit_ids']):raise ValueError('Invalid transfer')
        actual[key]=set(p['unit_ids']);transfer_ids.extend(p['unit_ids'])
    if actual!=dict(expected_transfers) or len(set(transfer_ids))!=len(transfer_ids):raise ValueError('Transfer/assignment mismatch')
    if sum(met.values())!=result['summary']['total_met']:raise ValueError('Incorrect summary')
