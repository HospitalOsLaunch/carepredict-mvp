"""HOWM-INT-1 public rule policies (no learning): historical rule, robust public rule, exploratory admissible.
Every policy receives only (public stream, public engine, catalogue, admissibility) of its own history."""

from __future__ import annotations

from typing import Any

from hospitalos.howm.keys import key, u


def historical(**kw: Any) -> dict:
    """Frozen historical practice: coordination/compatibility when admissible, otherwise nothing."""
    return kw["cat"][1] if kw["adm"][1] else kw["cat"][0]


def robust(**kw: Any) -> dict:
    """Robust public rule (thresholds fixed a priori, not tuned on any comparison): relieve the most backlogged shared
    resource on the first slot; else purchase external slots if patients are blocked; else coordinate; else nothing."""
    eng, cat, adm = kw["peng"], kw["cat"], kw["adm"]
    by = {a["id"]: (a, ok) for a, ok in zip(cat, adm)}
    dirty = sum(b.state == "dirty" for b in eng.beds.values())
    present = [s for s in eng.stays.values() if s.departed is None]
    wait_tr = sum(1 for s in present if s.ready and s.transport and s.tr_end is None)
    if dirty >= 2 * eng.base_c_cl and by.get("cl_w1", (None, False))[1]:
        return by["cl_w1"][0]
    if wait_tr >= 2 * eng.base_c_tr and by.get("tr_w1", (None, False))[1]:
        return by["tr_w1"][0]
    if eng.aval_blocked and by.get("av", (None, False))[1]:
        return by["av"][0]
    return historical(**kw)


def exploratory(**kw: Any) -> dict:
    """Uniform admissible action, keyed by (episode, decision tick): reproducible, policy-independent stream."""
    cat, adm, sp, t = kw["cat"], kw["adm"], kw["spec"], kw["t"]
    ok = [a for a, f in zip(cat, adm) if f]
    return ok[int(u(key("INT-explore", sp.part, sp.idx, sp.ekey), 0, "pick", t) * len(ok))]


RULES = {"historical": historical, "robust": robust, "exploratory": exploratory}
