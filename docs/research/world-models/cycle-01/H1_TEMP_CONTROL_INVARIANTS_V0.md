# WM-DISCOVERY-01/H1-TEMP — Negative-control invariants (review draft)

**Status:** DRAFT / NOT PREREGISTERED / NO EXPERIMENT AUTHORIZATION. Nothing in this file authorizes reading held-out data, training or computing model forwards.

**Stable namespace:** `WM-DISCOVERY-01/H1-TEMP` refers to the first hypothesis from the Nov 2026 lab, not the action-conditioned H1 in the charter; it corresponds to the temporal H2 in that charter. Historical names are not renamed.

## Falsifiable claim (restricted)

Under as-of-correct information and matched computational/information budgets, *event order* can provide additional **predictive utility** for a pre-specified H+24 outcome beyond a strong order-free summary. An improvement is not causal identification, identifiability of a latent state, or useful intervention simulation.

## Candidate comparisons — assumptions must be audited first

| ID | Proposed witness/comparator | Invariants to demonstrate | Failure interpretation |
|---|---|---|---|
| C0 | Robust order-free statistics with last value, recency, lags summary, masks, delays, calendar, site/regime | admissible history and information budget; train-only statistics; comparable capacity and tuning | incremental gain must beat this strong summary, not only a trivial mean |
| C1 | Explicit-lags/simple temporal forecasting reference | same targets/origins and train/validation budget | distinguishes value of order from value of a *latent JEPA architecture* |
| N1 | Conditional past-future *block* mismatch in pre-origin-defined strata | site, unit, hour, known regime, marginal distributions, missingness, observation delays, nonoverlap/support | bad artificial trajectories or broken support make mismatch non-discriminative |
| N2 | Order perturbation in train-fitted innovation blocks, preserving the recent observed anchor | last observed value, recency, conditional residual margins, masks, support | not guaranteed to preserve all autocorrelation; sensitivity alone is not a proof |
| N3 | Observation-process-only model (mask, age, latency, routine) | availability-as-of, site/regime comparability | does not claim latent dynamics; tests acquisition-policy shortcuts |
| H0 | Null perturbation / unchanged mapping for each witness | exact repeated input and output binding | mismatch between null and original is a technical failure |

**Important distinction:** fitting a model on permuted training pairs and shuffling features only at evaluation test different properties. Record which intervention is performed; do not pool the results.

## Required pre-registered audits

1. Define `event_at`, `available_at`, and revision rules for each observed input. Future targets never enter the features.
2. Report distributional differences after each negative control: site×regime×hour profiles, last value and age, missingness, lag-1/6/24h autocorrelation, out-of-support or impossible trajectories, and origin overlap.
3. Choose target units, primary loss (MSE for a continuous target if appropriate, not arbitrary Brier), absolute utility delta, confidence intervals, multiplicity, and sample-size/power *before* held-out evaluation.
4. Keep model capacity, optimization, number of fitted variants, and preprocessing/normalization comparable; when impossible, report non-identifiability of the contrast.
5. Select the best admissible comparator on train/validation, not the final holdout. Purge overlapping contexts and target windows; hold out sites/regimes/generator seeds as appropriate.
6. Report independent clustered uncertainty by site/time, individual-site disagreements, performance regressions and abstention conditions. Do not treat origins, models or their overlapping windows as independent replicates.

## Gates

- Technical witness with irreducible confounding or nonphysical trajectories: `NOT_DISCRIMINATIVE`.
- Unknown target or unsupported use of test data: `G1_NOT_FROZEN`.
- Scientific claims remain `NOT_TESTED` until a separate authorized, pre-registered experiment.
- G1 requires **human scientific review**. G2 new-compute authorization remains `NO_GO`, even if G1 review approves the protocol. No model promotion.

All internal effect sizes, experimental receipts, dataset identifiers and unpublished hypotheses reside in a private dossier.
