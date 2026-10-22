"""Short-history panel models; every validation fold holds out a whole date."""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import PoissonRegressor
from blood_assessment.contracts import GROUPS

METHODS = ('last', 'mean', 'ewm', 'poisson')

def panel(snapshot, quality):
    rows = snapshot.tables['daily_usage']
    df = pd.DataFrame(rows)
    df['units_used'] = df.units_used.astype(float)
    today = snapshot.as_of.date().isoformat()
    df = df[(df.date < today) & ~df.date.isin(quality['partial_dates'])]
    hospitals = sorted(r['site_id'] for r in snapshot.tables['sites'] if r['type']=='hospital')
    if df.empty: raise ValueError('No complete observed dates')
    if quality['sparse_reconciled']:
        idx = pd.MultiIndex.from_product([sorted(df.date.unique()), hospitals, GROUPS], names=['date','site_id','blood_type'])
        df = df.set_index(['date','site_id','blood_type']).reindex(idx).reset_index()
        df['units_used'] = df.units_used.fillna(0.)
    return df[['date','site_id','blood_type','units_used']].sort_values(['date','site_id','blood_type'])

def baseline(train, keys, method, policy):
    out = []
    for site, blood in keys:
        y = train[(train.site_id==site)&(train.blood_type==blood)].sort_values('date').units_used.tail(policy.window)
        prior = float(train[train.blood_type==blood].units_used.mean())
        if y.empty: value = prior
        elif method == 'last': value = float(y.iloc[-1])
        elif method == 'ewm': value = float(y.ewm(alpha=policy.alpha, adjust=False).mean().iloc[-1])
        else: value = float(y.mean())
        # Two pooled pseudo-days for sparse series, including zero recent observations.
        if len(y) and (y.gt(0).sum() < 3): value = (len(y)*value + 2*prior)/(len(y)+2)
        out.append(max(0., value))
    return np.array(out)

def features(train, keys):
    rows=[]
    for site,blood in keys:
        y = train[(train.site_id==site)&(train.blood_type==blood)].sort_values('date').units_used
        rows.append({'site_id':site,'blood_type':blood,'lag':float(y.iloc[-1]) if len(y) else 0., 'trailing':float(y.tail(3).mean()) if len(y) else 0.})
    return pd.DataFrame(rows)

def poisson(train, keys):
    xs, ys = [], []
    dates = sorted(train.date.unique())
    for day in dates[2:]:
        target = train[train.date==day]
        xs.append(features(train[train.date < day], list(zip(target.site_id,target.blood_type))))
        ys.extend(target.units_used.tolist())
    if not xs: raise ValueError('Insufficient training dates')
    if sum(ys)==0: return np.zeros(len(keys))
    preprocess = ColumnTransformer([('ids',OneHotEncoder(handle_unknown='ignore'),['site_id','blood_type']), ('counts',StandardScaler(),['lag','trailing'])])
    model = make_pipeline(preprocess, PoissonRegressor(alpha=1., max_iter=500, tol=1e-7))
    model.fit(pd.concat(xs,ignore_index=True), np.array(ys))
    return np.maximum(0., model.predict(features(train,keys)))

def compare(df, policy):
    dates=sorted(df.date.unique())
    results={m: {'errors':[], 'actual':[], 'fold_dates':[]} for m in METHODS}
    for day in dates[3:]:
        train, test = df[df.date<day], df[df.date==day]
        keys=list(zip(test.site_id,test.blood_type))
        for method in METHODS:
            if method=='poisson' and train.date.nunique()<policy.min_ml_days: continue
            try: pred=poisson(train,keys) if method=='poisson' else baseline(train,keys,method,policy)
            except (ValueError, FloatingPointError): continue
            r=results[method]
            r['errors'].extend((pred-test.units_used.to_numpy()).tolist())
            r['actual'].extend(test.units_used.tolist())
            r['fold_dates'].append({'train_end':max(train.date),'test_date':day})
    metrics={}
    for m,r in results.items():
        e=np.array(r['errors']); denom=sum(r['actual'])
        metrics[m]={'mae':float(np.abs(e).mean()) if len(e) else None, 'wape':float(np.abs(e).sum()/denom) if denom else None, 'signed_bias':float(e.mean()) if len(e) else None,'folds':len(r['fold_dates']),'observations':len(e),'horizons':[1] if len(e) else [],'fold_dates':r['fold_dates'],'zero_denominator':denom==0}
    # Keep trailing mean unless five or more date folds support >10% improvement.
    selected='mean'
    eligible=[m for m in METHODS if metrics[m]['folds']>=5 and metrics[m]['mae'] is not None]
    if eligible and metrics['mean']['mae']:
        best=min(eligible,key=lambda m:metrics[m]['mae'])
        if metrics[best]['mae'] < .9*metrics['mean']['mae']: selected=best
    status='insufficient_history' if len(dates)<policy.min_ml_days else ('eligible' if selected=='poisson' else 'baseline_preferred')
    return {'selected':selected,'ml_status':status,'provisional':True,'metrics':metrics,'limitation':'Only one-day held-out horizons; no validated seven-day accuracy.'}
