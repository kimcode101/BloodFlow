from collections import Counter, defaultdict
from datetime import date
from zoneinfo import ZoneInfo
from blood_assessment.contracts import GROUPS

class DataError(ValueError):
    pass

def validate(s):
    t = s.tables
    today = s.as_of.astimezone(ZoneInfo('Europe/Paris')).date()
    errors, warnings = [], []
    def check(ok, message):
        if not ok: errors.append(message)
    keys = {'sites': ('site_id',), 'units': ('unit_id',), 'transfers': ('transfer_id',), 'travel_times': ('from_site_id','to_site_id'), 'daily_usage': ('date','site_id','blood_type'), 'planned_activity': ('activity_id',)}
    for table, fields in keys.items():
        vals = [tuple(r.get(k) for k in fields) for r in t[table]]
        check(len(set(vals)) == len(vals), f'duplicate:{table}')
    sites = {r['site_id']: r for r in t['sites']}
    check(set(sites) == {'H1','H2','H3','H4','B1','B2','X1'}, 'unexpected site IDs')
    hospitals = [k for k,r in sites.items() if r['type'] == 'hospital']
    for r in sites.values():
        check(r['type'] in ('hospital','blood_bank','external'), 'site type')
        check(not r.get('home_bank_id') or sites.get(r['home_bank_id'], {}).get('type') == 'blood_bank', 'home bank FK')
        if not r.get('lat') or not r.get('lon'): warnings.append('missing coordinates:' + r['site_id'])
    actual, declared = Counter(), {}
    units = {u['unit_id']: u for u in t['units']}
    for u in t['units']:
        check(u['blood_type'] in GROUPS and u['storage_site'] in sites, 'unit FK/group')
        collected, expiry = date.fromisoformat(u['collection_date']), date.fromisoformat(u['expiry_date'])
        check(collected <= today and expiry > collected, 'unit chronology')
        check(u['status'] in ('available','used','expired'), 'unit status')
        if u['status'] == 'used':
            used = date.fromisoformat(u['used_date'])
            check(collected <= used < expiry and used <= today and u['storage_site'] in hospitals, 'used chronology/site')
            actual[(u['used_date'],u['storage_site'],u['blood_type'])] += 1
        else:
            check(not u['used_date'], 'unused unit has used_date')
        if u['status'] == 'available' and expiry <= today:
            warnings.append('available but ineligible at expiry cutoff:units/' + u['unit_id'])
    partial_dates = set()
    for r in t['daily_usage']:
        d = date.fromisoformat(r['date'])
        check(d <= today and r['site_id'] in hospitals and r['blood_type'] in GROUPS, 'usage date/FK/group')
        check(int(r['units_used']) >= 0 and r['partial_day'].lower() in ('true','false'), 'usage quantity/partial flag')
        if r['partial_day'].lower() == 'true': partial_dates.add(r['date'])
        check(d != today or r['partial_day'].lower() == 'true', 'analysis-day usage must be partial')
        declared[(r['date'],r['site_id'],r['blood_type'])] = int(r['units_used'])
    reconciled = all(actual[k] == declared.get(k, 0) for k in set(actual) | set(declared))
    check(reconciled, 'daily_usage does not reconcile with used units; missing rows cannot become zeros')
    # Reconciliation is conditional on the snapshot containing the complete used-unit ledger.
    warnings.append('Sparse zeros conditional on supplied used-unit ledger completeness; no external completeness proof.')
    dates = sorted({r['date'] for r in t['daily_usage']})
    check(bool(dates), 'no usage history')
    moves = defaultdict(list)
    for r in t['transfers']:
        u = units.get(r['unit_id'])
        check(u is not None and r['from_site_id'] in sites and r['to_site_id'] in sites, 'transfer FK')
        if u:
            d = r['transfer_date']
            check(u['collection_date'] <= d < u['expiry_date'] and d <= today.isoformat() and (not u['used_date'] or d <= u['used_date']), 'transfer chronology')
        check(r['from_site_id'] != r['to_site_id'], 'self transfer')
        moves[r['unit_id']].append(r)
    for uid, rows in moves.items():
        rows = sorted(rows, key=lambda r:r['transfer_date'])
        if len({r['transfer_date'] for r in rows}) != len(rows):
            warnings.append('same-day transfer order unresolved:units/' + uid)
            continue
        for a,b in zip(rows,rows[1:]): check(a['to_site_id'] == b['from_site_id'], 'broken transfer chain')
        if uid in units: check(rows[-1]['to_site_id'] == units[uid]['storage_site'], 'final transfer location')
    unresolved = []
    for r in t['planned_activity']:
        date.fromisoformat(r['date'])
        check(r['site_id'] in hospitals, 'planned site')
        check(not r['blood_type'] or r['blood_type'] in GROUPS, 'planned group')
        check(not r['units_expected'] or int(r['units_expected']) > 0, 'planned quantity')
        check(not r['priority'] or r['priority'] in ('elective','scheduled-critical','scheduled_critical'), 'planned priority')
        if any(not r.get(k) for k in ('blood_type','units_expected','procedure','priority')):
            unresolved.append('planned_activity/' + r['activity_id'])
    links = set()
    for r in t['travel_times']:
        check(r['from_site_id'] in sites and r['to_site_id'] in sites, 'route FK')
        links.add((r['from_site_id'],r['to_site_id']))
        for k in ('distance_km','minutes_normal','minutes_rush'):
            check(r.get(k) is None or float(r[k]) >= 0, 'negative route value')
    for h in hospitals:
        if (sites[h]['home_bank_id'], h) not in links: warnings.append('missing home-bank route:' + h)
    if errors: raise DataError('; '.join(sorted(set(errors))))
    return {'valid': True, 'sparse_reconciled': reconciled, 'partial_dates': sorted(partial_dates), 'warnings': sorted(set(warnings)), 'unresolved_planned': unresolved, 'totals': {**{k:len(v) for k,v in t.items()}, 'available':sum(u['status']=='available' for u in t['units']), 'used':sum(actual.values())}}
