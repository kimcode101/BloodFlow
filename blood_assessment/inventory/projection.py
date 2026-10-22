from datetime import date, timedelta
from math import ceil

def usable(snapshot, site, blood, day):
    return sorted([u for u in snapshot.tables['units'] if u['status']=='available' and u['storage_site']==site and u['blood_type']==blood and date.fromisoformat(u['expiry_date'])>day], key=lambda u:(u['expiry_date'],u['unit_id']))

def project(units, daily_demands):
    """Fractional expected-use simulation; actual allocation stays whole-unit.

    Expiry is exclusive: a unit dated D cannot be used on D. No arrivals implicit.
    """
    pool=[dict(u, remaining=1.) for u in units]
    pool.sort(key=lambda u:(u['expiry_date'],u['unit_id']))
    result=[]
    for day,demand in daily_demands:
        if demand<0: raise ValueError('Negative demand')
        expired=sum(u['remaining'] for u in pool if u['expiry_date']<=day.isoformat())
        pool=[u for u in pool if u['expiry_date']>day.isoformat() and u['remaining']>1e-12]
        unmet=float(demand)
        for u in pool:
            take=min(u['remaining'],unmet)
            u['remaining']-=take; unmet-=take
            if unmet<=1e-12: break
        result.append({'date':day.isoformat(),'demand':demand,'demand_met':demand-unmet,'unmet_demand':max(0.,unmet),'usable_closing_inventory':sum(u['remaining'] for u in pool),'units_expiring_unused':expired})
    return {'days':result,'first_shortage_date':next((r['date'] for r in result if r['unmet_demand']>1e-9),None),'unmet_demand':sum(r['unmet_demand'] for r in result),'units_expiring_unused':sum(r['units_expiring_unused'] for r in result),'assumption':'Fractional expected demand FEFO, exclusive date expiry; no future receipts.'}

def expiry_exposure(units, today):
    return {str(n):sum(today < date.fromisoformat(u['expiry_date']) <= today+timedelta(days=n) for u in units) for n in (1,3,5,7)}

def target(requirements, buffer):
    base=sum(requirements)
    return ceil(base*(1+buffer)), {'planning_sum':base, 'buffer_fraction':buffer, 'buffer_units':base*buffer,'rounding':'ceiling once after summing'}
