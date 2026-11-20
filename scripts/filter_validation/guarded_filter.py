"""Conservative candidate: infer cleaning/placement, retain declared transport.

V3 independent testing found significant transport-count regression at 60min lag.
Transport completion inference is disabled for every delay until a new model
passes a fresh calibration gate. This is a global gate, not a fitted threshold.
"""
from correction import posterior as experimental_posterior


class DeclaredService:
    def unfinished(self, age):
        return 1.0


def posterior(pe, ps, laws, draw, provider):
    guarded_laws = dict(laws, transport=DeclaredService())
    result = experimental_posterior(pe, ps, guarded_laws, draw, provider)
    assert set(result.tr_service) == set(pe.tr_service)
    return result
