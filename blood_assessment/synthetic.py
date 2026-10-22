"""Reproducible what-if inputs; never modifies the base snapshot."""
from copy import deepcopy
from datetime import timedelta
from random import Random
from blood_assessment.data_access.snapshot import make_snapshot
from blood_assessment.data_access.validation import validate


def generate(snapshot, seed, kind='demand_surge'):
    rng = Random(seed)
    tables = deepcopy(snapshot.tables)
    today = snapshot.as_of.date()
    changes = []
    if kind in ('demand_surge', 'mixed'):
        for i in range(rng.randint(2, 4)):
            site, group = rng.choice(['H1','H2','H3','H4']), rng.choice(['O-','A-','O+','A+'])
            units = rng.randint(12, 35)
            day = (today+timedelta(days=rng.randint(1,2))).isoformat()
            identity = f'sim-{seed}-activity-{i}'
            tables['planned_activity'].append(dict(activity_id=identity,site_id=site,date=day,
                procedure='SIMULATED demand surge',blood_type=group,units_expected=str(units),priority='scheduled-critical'))
            changes.append(dict(type='added_demand',site_id=site,blood_type=group,units=units,date=day,source_ref='planned_activity/'+identity))
    if kind in ('donation', 'mixed'):
        bank, group = rng.choice(['B1','B2']), rng.choice(['O-','A-','O+','A+'])
        units = rng.randint(15,40)
        for i in range(units):
            tables['units'].append(dict(unit_id=f'sim-{seed}-unit-{i}',blood_type=group,storage_site=bank,
                collection_date=today.isoformat(),expiry_date=(today+timedelta(days=42)).isoformat(),
                status='available',used_date=None,is_synthetic='True'))
        changes.append(dict(type='added_donation',site_id=bank,blood_type=group,units=units,date=today.isoformat()))
    result = make_snapshot(tables,snapshot.as_of,snapshot.dataset_schema,f'synthetic-button-v1:{seed}:{kind}')
    validate(result)
    return result, {'seed':seed,'kind':kind,'changes':changes,'base_snapshot_id':snapshot.snapshot_id,
                    'snapshot_id':result.snapshot_id,'generator_version':'synthetic-button-v1',
                    'note':'Independent what-if snapshot; every click starts from the original fixture. No real event or shipment.'}
