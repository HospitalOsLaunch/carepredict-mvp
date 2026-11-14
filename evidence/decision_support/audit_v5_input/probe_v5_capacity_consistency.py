"""Bounded neighbouring synthetic probes; no fitting, network, or external action."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from test_v4_resource_boundaries import loan_data, offer, snap, only
from hospitalos.decision_support.planner import simulate, recommend, review, ReviewStore


def attempt(obs, at, settings, order):
    s = snap(obs, at, settings)
    store = ReviewStore()
    actions=[]
    for ident in order:
        rec = simulate(s, only(ident), settings)
        result = review(rec, 'approve', s, at, f'v5-probe-{ident}', store)
        actions.append({'option':ident, 'recommendation_status':rec.status,
                        'approvable':rec.approvable, 'review':result.model_dump(mode='json')})
    held={f'{res}@{slot}':len(keys) for (res,slot),keys in store.ledger.used.items() if res.startswith('lend:')}
    capacities={f'{res}@{slot}':v for (res,slot),v in store.ledger.capacity.items() if res.startswith('lend:')}
    return {'actions':actions,'lender_holds':held,'lender_capacity':capacities,'conflicts':store.ledger.conflicts}

obs,at,settings=loan_data(scheduled=4)
offer(obs,'R2')['lending_unit_scheduled']=5
s=snap(obs,at,settings);rec=recommend(s,settings)
out={
 'test':'V5 consistent capacity of same lender / same snapshot / same hours',
 'input':{'as_of':at.isoformat(),'R1':offer(obs,'R1'),'R2':offer(obs,'R2')},
 'R1_then_R2':attempt(obs,at,settings,['R1','R2']),
 'R2_then_R1':attempt(obs,at,settings,['R2','R1']),
 'combined_candidate':{'rejected':rec.bundle.search.rejected},
}
# Positive control: current state genuinely has two available slots for both offers.
okobs=deepcopy(obs);offer(okobs,'R1')['lending_unit_scheduled']=5
out['positive_consistent_capacity_5']=attempt(okobs,at,settings,['R1','R2'])
# Positive control: snapshot timestamps not aligned to an hour are explicitly rejected.
try:
    snap(obs,at+timedelta(minutes=30),settings)
except ValueError as exc:
    out['positive_offgrid_snapshot_rejected']=str(exc)
else:
    out['positive_offgrid_snapshot_rejected']=False
Path('/mnt/data/ds_v5_independent_audit/evidence/capacity_consistency_probes.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
for name in ['R1_then_R2','R2_then_R1','positive_consistent_capacity_5']:
    x=out[name]
    print(name,[(a['option'],a['review']['outcome']) for a in x['actions']],x['lender_holds'])
print('combined rejection',out['combined_candidate'])
print('offgrid snapshot rejected',bool(out['positive_offgrid_snapshot_rejected']))
