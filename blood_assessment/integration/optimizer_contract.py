"""Optional aggregate plugin interface. Default dated solver is in optimization/."""
from typing import Protocol
from datetime import timedelta
from math import ceil
from pydantic import Field
from blood_assessment.contracts import Contract, Blood, Requirement
from blood_assessment.inventory.projection import usable
from blood_assessment.integration.optimizer import validate_proposals

class Allocation(Contract):
    from_site_id: str
    to_site_id: str
    blood_type: Blood
    units: int = Field(gt=0,strict=True)
    unit_ids: list[str]

class Optimizer(Protocol):
    def solve(self, inputs: dict) -> list[Allocation]: ...

def external_preview(optimizer, snapshot, assessment, policy):
    day=snapshot.as_of.date()+timedelta(days=1)
    sites={s['site_id']:s for s in snapshot.tables['sites']}
    from blood_assessment.contracts import GROUPS
    required={f'{s}/{b}' for s,r in sites.items() if r['type']=='blood_bank' for b in GROUPS}
    if set(policy.reserves)!=required or any(type(v) is not int or v<0 for v in policy.reserves.values()):
        raise ValueError('Explicit reserves required for every bank/group')
    inputs={'version':'1','snapshot_id':snapshot.snapshot_id,'assessment_id':assessment.assessment_id,'allocation_date':day.isoformat(),'blood_groups':list(GROUPS),'sites':snapshot.tables['sites'],'travel_times':snapshot.tables['travel_times'],'distance_semantics':'road factor 1.3; compute Haversine from coordinates if aerial distance is needed','requirements':[r.model_dump() for r in assessment.proposed_requirement_updates],'protected_reserves':policy.reserves,'eligible_units':[u for u in snapshot.tables['units'] if u['status']=='available' and u['expiry_date']>day.isoformat()],'remaining_today_by_site_group':[{'site_id':r['site_id'],'blood_type':r['blood_type'],'units':ceil(r['remaining_today'] or 0)} for r in assessment.findings],'hypothetical_only':True}
    from copy import deepcopy
    proposals=[Allocation.model_validate(x).model_dump() for x in optimizer.solve(deepcopy(inputs))]
    result={'snapshot_id':snapshot.snapshot_id,'assessment_id':assessment.assessment_id,'adapter':'configured_graph_optimizer','status':'hypothetical_only','inputs':inputs,'transfer_proposals':proposals}
    validate_proposals(snapshot,result,policy,day)
    # Fail closed on absent links, external donors, bad destinations or excess inbound.
    routes={(r['from_site_id'],r['to_site_id']):r for r in snapshot.tables['travel_times']}
    inbound={}
    for p in proposals:
        route=routes.get((p['from_site_id'],p['to_site_id']))
        if sites.get(p['from_site_id'],{}).get('type')!='blood_bank' or sites.get(p['to_site_id'],{}).get('type')!='hospital': raise ValueError('Only configured bank-to-hospital routes supported')
        if not route or not route.get('minutes_rush') or int(route['minutes_rush'])>1440: raise ValueError('Unavailable route')
        key=(p['to_site_id'],p['blood_type']); inbound[key]=inbound.get(key,0)+p['units']
    for req in assessment.proposed_requirement_updates:
        key=(req.site_id,req.blood_type)
        finding=next(r for r in assessment.findings if (r['site_id'],r['blood_type'])==key)
        local=max(0,len(usable(snapshot,*key,day))-ceil(finding['remaining_today'] or 0))
        if inbound.get(key,0)>max(0,req.target-local): raise ValueError('Exceeds approved target deficit')
    return result
