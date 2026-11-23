"""Stage-specific trajectory models, fitted to factual and paired simulated paths."""
from itertools import chain

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.preprocessing import StandardScaler

from sim import PLANS


def scenarios(dataset):
    return ((site, case) for site in dataset for case in site['cases'])


def context(site, case, stage):
    if stage == '08':
        return (np.r_[site['morning'],site['latents']],np.array(site['forecast']),list(range(len(PLANS))))
    indices=[i for i,p in enumerate(PLANS) if p[0]==stage]
    row=case['rows'][indices[0]]
    public=np.r_[row['noon'],row['latents']]
    predicted=[case['rows'][i]['midday_forecast'] for i in indices]
    return np.array(public), np.array(predicted), indices


def features(public, estimate):
    # Keep the same input information for direct and paired regressions.
    return np.r_[public, estimate[:,:6].ravel()]


class ResponseModel:
    def fit(self,x,y):
        self.shape=y.shape[1:]
        flat=y.reshape(len(y),-1)
        self.scaler=StandardScaler().fit(flat)
        self.forest=ExtraTreesRegressor(n_estimators=80,min_samples_leaf=2,random_state=20261120)
        self.forest.fit(x,self.scaler.transform(flat))
        return self

    def __call__(self,x):
        flat=self.scaler.inverse_transform(np.asarray(self.forest.predict(x[None])).reshape(1,-1))
        return flat.reshape(self.shape)


def fit_models(dataset):
    models={}
    for stage in chain(['08'], dict(PLANS)):
        xx,yy=[],[]
        for site, case in scenarios(dataset):
            public,prior,indices=context(site,case,stage)
            xx.append(features(public,prior))
            label='full' if stage=='08' else 'future'
            yy.append([case['rows'][i][label] for i in indices])
        y=np.array(yy)
        models[stage]=[ResponseModel().fit(xx,target) for target in (y,y[:,:1],y-y[:,:1])]
    return models


def estimate(models,site,case,stage,method):
    public,prior,ids=context(site,case,stage)
    if method=='simulation':
        return prior,ids
    x=features(public,prior)
    direct,base,difference=models[stage]
    pred=direct(x) if method=='direct' else base(x)+difference(x)
    pred=np.maximum(0,pred)
    pred[:,3]=np.clip(pred[:,3],0,1)
    return pred,ids


def choose(pred,penalty):
    # Equal spend. Penalise care/transfer increases vs the public simulator's
    # fixed first alternative in this stage (same reference in every model).
    increase=np.maximum(pred[:,1:3]-pred[:1,1:3],0)
    return int(np.argmin(pred[:,0]+penalty*increase.sum(1)))


def decide(site,case,method,models=None,penalty=0,fixed=0):
    if method=='fixed':
        return fixed,fixed,None,None
    forecast,ids=estimate(models,site,case,'08',method)
    plan=ids[choose(forecast,penalty)]
    update,ids=estimate(models,site,case,PLANS[plan][0],method)
    local=choose(update,penalty)
    return plan,ids[local],forecast[plan],update[local]


def dev_headroom(dev):
    actual=[];bench=[];oracle=[]
    for site,case in scenarios(dev):
        costs=np.array([r['full'][0] for r in case['rows']])
        _,i,_,_=decide(site,case,'simulation')
        actual.append(costs)
        bench.append(costs[i])
        oracle.append(costs.min())
    fixed=int(np.argmin(np.mean(actual,0)))
    reference=min(np.mean(bench),np.mean(np.asarray(actual)[:,fixed]))
    return dict(fixed=fixed,simulation=float(np.mean(bench)),fixed_cost=float(np.mean(np.asarray(actual)[:,fixed])),
                optimistic=float(np.mean(oracle)),maximum_percent=float(100*(1-np.mean(oracle)/reference)))
