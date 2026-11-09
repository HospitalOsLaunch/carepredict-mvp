# WM-DISCOVERY-01/H1-TEMP — Negative-control invariants (review draft)

**Status:** DRAFT / NOT PREREGISTERED / NO EXPERIMENT AUTHORIZATION. Nothing in this file authorizes reading held-out data, training or computing model forwards.

**Stable namespace:** `WM-DISCOVERY-01/H1-TEMP` refers to the first hypothesis from the Nov 2026 lab, not the action-conditioned H1 in the charter; it corresponds to the temporal H2 in that charter. Historical names are not renamed.

## Falsifiable claim (restricted)

**H1a (temporal information):** under as-of-correct information and matched budgets, an ordered predictor provides additional predictive utility for a specified H+24 outcome beyond a robust **order-attenuated** summary.\n\n**H1b (latent representation):** under matched budgets, a JEPA/RSSM representation improves upon a strong explicit temporal baseline using lagged values and other admissible time features. H1a may pass while H1b fails. Neither result demonstrates causal identification, unique latent state, or useful intervention simulation.\n\n**Terminology correction:** a summary that retains last value, recency or lags is **not strictly order-free**. These anchors already encode temporal information; the estimand is incremental value beyond those anchors.

## Candidate comparisons — assumptions must be audited first

| ID | Proposed witness/comparator | Invariants to demonstrate | Failure interpretation |
|---|---|---|---|
| C0 | Robust **order-attenuated** summaries with distributions, last value, recency, masks, delays, calendar, as-of-known site/regime; no unannounced explicit lags | admissible history and information budget; train-only statistics; comparable capacity and tuning | **H1a** must beat this strong anchored summary, not merely a trivial mean; C0 already retains some temporal information |
| C1 | Explicit-lags / simple temporal forecasting reference (strong lags, seasonality, linear or analogous model) | same targets/origins, as-of features and train/validation budget | **H1b** separates value of temporal order from a specifically latent JEPA/RSSM advantage |
| N1 | Conditional past-future *block* mismatch in pre-origin-defined strata | site, unit, hour, known regime, marginal distributions, missingness, observation delays, nonoverlap/support | bad artificial trajectories or broken support make mismatch non-discriminative |
| N2 | Naturally observed matched-order contrasts first; train-fitted innovations permutation only if conditional exchangeability is explicitly checked | last observed value, recency, conditional residual margins, masks, support | cannot preserve *all* temporal structure while destroying order; invalid exchangeability or support => `NOT_DISCRIMINATIVE` |
| N3 | Observation-process-only model (mask, age, latency, routine) | availability-as-of, site/regime comparability | does not claim latent dynamics; tests acquisition-policy shortcuts |
| N0 | Null perturbation / unchanged mapping for each witness | exact repeated input and output binding | mismatch between null and original is a technical failure |

**Important distinction:** fitting a model on permuted training pairs and shuffling features only at evaluation test different properties. Record which intervention is performed; do not pool the results.

## Present evidence boundary (10 November 2026)\n\nThe verified archived `panel_balance.csv` is a **score and error-component table**, not a timestamped observation stream. It cannot establish `available_at`, revision behaviour, temporal support for N1/N2, or the exchangeability needed by an innovation witness. Any claim that the proposed controls have already passed their scientific invariants is **not supported**. A genuinely new, authorized as-of dataset is needed before tests; the historically consulted development panel is not a blind confirmatory holdout. The numeric utility thresholds for H1a/H1b remain unset pending clinical-operational rationale and power analysis.\n\n## Required pre-registered audits

1. Define `event_at`, `available_at`, and *version-specific* revision availability for each observed input, distinguishing delayed entry from a historical event. Future targets never enter the features.
2. Report distributional differences after each negative control: site×regime×hour profiles, last value and age, missingness, lag-1/6/24h autocorrelation, out-of-support or impossible trajectories, and origin overlap.
3. Choose target units, primary loss (MSE for a continuous target if appropriate, not arbitrary Brier), absolute utility delta, confidence intervals, multiplicity, and sample-size/power *before* held-out evaluation.
4. Keep model capacity, optimization, number of fitted variants, and preprocessing/normalization comparable; when impossible, report non-identifiability of the contrast. Avoid conditioning witness strata on a regime defined retrospectively using future outcomes.
5. Select the best admissible comparator on train/validation, not the final holdout. Purge overlapping contexts and target windows; hold out sites/regimes/generator seeds as appropriate.
6. Report independent clustered uncertainty by site/time, individual-site disagreements, performance regressions and abstention conditions. Do not treat origins, models or their overlapping windows as independent replicates.

## Gates

- Technical witness with irreducible confounding or nonphysical trajectories: `NOT_DISCRIMINATIVE`.
- Unknown target or unsupported use of test data: `G1_NOT_FROZEN`.
- Scientific claims remain `NOT_TESTED` until a separate authorized, pre-registered experiment.
- G1 requires **human scientific review**. G2 new-compute authorization remains `NO_GO`, even if G1 review approves the protocol. No model promotion.

All internal effect sizes, experimental receipts, dataset identifiers and unpublished hypotheses reside in a private dossier.
