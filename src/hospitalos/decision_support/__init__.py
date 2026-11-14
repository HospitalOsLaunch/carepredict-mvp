"""HospitalOS decision support, auto-first prototype (P0-P4).

The system observes a synthetic unit, forecasts habitual practice and proposes a plan by
itself; the manual X1/X2 scenario reuses the same engine to lock or modify hypotheses.
No action is ever sent to a hospital information system. Every output carries
scientific_status=PROTOTYPE_UNVALIDATED, clinical_validation=false and G2=NO-GO.
"""

ENGINE_VERSION = "ds-reference-0.1.0"
SCIENTIFIC_STATUS = "PROTOTYPE_UNVALIDATED"
