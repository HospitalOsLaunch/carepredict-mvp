# WM-DISCOVERY-01 — G1 scientific readiness (public summary)

**Date:** 2026-11-09. **Status:** DRAFT / NOT_FROZEN / NO_COMPUTE_AUTHORIZATION.

**Research aim:** Evaluate whether predictive representations of partially observable operational systems preserve useful event ordering beyond simple marginal statistics, recency, observation schedules, and temporal shortcuts.

This document contains no private experimental observations, numerical results, model weights, evidence journals or compute approval. Full scientific hypotheses and historical provenance are maintained in a separate access-controlled private dossier.

## Hypothesis identity and disambiguation

- `WM-DISCOVERY-01/H1-TEMP`: temporal predictive sufficiency, the first hypothesis selected by the **November 2026 research lab**.
- In the initial Cycle-01 charter, `H1` refers to **action-conditioned dynamics**, while the temporal hypothesis is `H2`.
- These identifiers belong to different naming namespaces. Keep historical labels unchanged; apply this mapping in all new scientific documents.

## Claims that are *not* established

A positive paired prediction improvement does **not** prove causal identification, a unique latent state, causal effects of policies, or deployment readiness. The candidate H1-TEMP claim is limited to *incremental prediction utility of temporal order in the specified evaluation domain*.

## Proposed gate protocol, not yet preregistered

1. Verify source manifests, sha256 fingerprints, target units, origin timestamps and available-at provenance, without altering historical evidence.
2. Specify the exact H+24 operational target and predefine a single primary loss appropriate to its scale and prediction type.
3. Choose strongest non-order controls using train/validation only; include persistence, seasonal, train-only mean, explicit recency/lags, missingness-only and relevant simple temporal models.
4. Specify marginal-preserving and observation-policy-preserving witnesses; formally audit what their transformations **do not** preserve. Do not equate shuffle sensitivity with causal discovery.
5. Freeze temporal purging, site/regime holdouts, uncertainty intervals and a prejustified operational utility threshold. **No arbitrary Brier 0.01** without a defined binary event and rationale.
6. Obtain a critical review from someone independent of the implementation. Remain **G2 NO-GO** until human authorization of an immutable preregistration and compute permit.

**Candidate test (to be locked only after the above):**

`Delta_order = Risk(best admissible non-order comparator) - Risk(ordered model)`.

Positive values indicate a *paired predictive advantage* under fair conditions, not a representation mechanism or intervention effect by themselves.

## Blocking conditions

- Incomplete as-of provenance, unseen retrospective revisions, leakage across folds.
- Comparator mismatched in information/regularization/tuning/budget.
- Witness corrupts support or introduces physically impossible sequences.
- Primary target/threshold selected using test outcomes.
- Missing reliable primary evidence, insufficient precision, or invalid attribution.
- No independent signed scientific review.

## Current decisions

| Review gate | Status |
|---|---|
| Scientific question formulated | READY FOR HUMAN REVIEW |
| Evidence hashes verified | PENDING |
| Novelty audit | INCOMPLETE |
| Preregistration frozen | NO |
| New ML execution | NOT AUTHORIZED |
| Model promotion | NO PROMOTION |

Do not merge this into `mvp/computer-use`; never use this public branch to upload patient data, internal receipts, private weights or unpublished experiment results.
