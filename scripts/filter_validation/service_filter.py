"""Censor-aware public service estimator. No true state is used for fitting or inference."""
from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr


@dataclass
class ServiceLaw:
    median: float
    sigma: float
    lag: float

    def mass(self, ages):
        ages = np.asarray(ages, dtype=float)
        upper = ndtr(np.log(np.maximum(ages, 1e-12)/self.median)/self.sigma)
        lower = ndtr(np.log(np.maximum(ages-15, 1e-12)/self.median)/self.sigma)
        return upper-lower

    def survival(self, age):
        edge = max(0, math.ceil(age/15)-1)*15
        return float(ndtr(-math.log(max(edge,1e-12)/self.median)/self.sigma))

    def unreported_completed(self, age):
        duration = np.arange(15, max(15, math.floor(age/15)*15)+1, 15)
        duration = duration[duration < age]
        if self.lag == 0 or not len(duration):
            return 0.
        # Reports are visible strictly before cutoff, so lag >= cutoff-duration remains unobserved.
        return float(np.sum(self.mass(duration)*np.exp(-(age-duration)/self.lag)))

    def unfinished(self, age):
        s = self.survival(age)
        return s / max(1e-300, s+self.unreported_completed(age))


def records(observations, cutoff, kind):
    visible = sorted((o for o in observations if o[1] < cutoff), key=lambda x:(x[0], x[2]))
    starts, completed = {}, {}
    for event, available, name, subject, _, _ in visible:
        if name == kind+"_start":
            starts[(subject,event)] = event
        if name == kind+"_done":
            previous = [key for key in starts if key[0]==subject and key[1]<event]
            if previous:
                key = max(previous, key=lambda x:x[1])
                completed[key] = (event-key[1], available-event)
    return [(cutoff-start, completed.get(key)) for key,start in starts.items()]


def fit(all_records, zero_lag=False):
    completed = [value for _,value in all_records if value is not None]
    if len(completed)<10:
        raise ValueError("Insufficient completed services")
    durations = np.array([d for d,_ in completed])
    lags = np.array([l for _,l in completed])
    censored = np.array([age for age,value in all_records if value is None])
    def make(x):
        return ServiceLaw(float(np.exp(x[0])),float(np.exp(x[1])),0. if zero_lag else float(np.exp(x[2])))
    def loss(x):
        law=make(x)
        total=-np.log(np.maximum(law.mass(durations),1e-300)).sum()
        if not zero_lag:
            total += (lags/law.lag).sum()-len(lags)*np.log(-np.expm1(-1/law.lag))
        for age in censored:
            total-=np.log(max(1e-300,law.survival(age)+law.unreported_completed(age)))
        return float(total)
    x=np.log([np.median(durations),.5,max(1,np.mean(lags))])
    result=minimize(loss,x,method="L-BFGS-B",bounds=[(np.log(10),np.log(600)),(np.log(.1),np.log(1.5)),(np.log(.1),np.log(1440))])
    if not result.success:
        raise RuntimeError(result.message)
    return make(result.x),dict(completed=len(completed),censored=len(censored),negative_log_likelihood=float(result.fun))


def candidates(ps,laws,now):
    """Public services for which no completion is yet known."""
    out=[]
    for bed_id,bed in sorted(ps.beds.items()):
        if bed.data.get("state")=="cleaning":
            start=bed.data["clean_start"]
            out.append(("cleaning",bed_id,start,laws["cleaning"].unfinished(now-start)))
    for sid,stay in sorted(ps.present_stays().items()):
        if "transport_start" in stay and "transport_done" not in stay:
            start=stay["transport_start"]
            out.append(("transport",sid,start,laws["transport"].unfinished(now-start)))
    return out
