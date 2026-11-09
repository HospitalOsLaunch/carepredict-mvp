# HospitalOS World Models Research Lab — Cycle 01

**Cycle:** 2026-11-10 to 2026-12-09 (Europe/Paris)  
**Status:** planning only / NO EXPERIMENT AUTHORIZATION  
**Scope:** scientific research protocols, not production or pilot deployment.

## Research question

Under partial observability, how can a learned representation preserve information about temporal dynamics and intervention-dependent transitions, rather than exploiting static marginal statistics, observation-policy shortcuts, or temporal leakage?

This is a research question, not a statement that the current system possesses identified causal dynamics.

## Candidate hypotheses (not established innovations)

- **H1 — Action-conditioned latent dynamics:** action-diverse histories yield distinguishable action-dependent transitions under appropriate assumptions.
- **H2 — Temporal observability:** an as-of-correct predictive representation must outperform equally informed controls whose temporal alignment is disrupted.
- **H3 — Belief-state representation:** explicitly tracking uncertainty under observation gaps improves out-of-distribution decision-relevant predictions.

For each hypothesis, record prior art, novelty boundary, falsifiable prediction, possible confounds, cheapest discriminating experiment, and stopping criterion.

## Role separation

Research director; prior-art reviewer; hypothesis scientist; experiment designer; adversarial falsifier; ML engineer; independent evaluator. Different role names do not imply independent evidence when powered by the same underlying model.

## Four-week protocol

| Week | Dates | Expected deliverable | Gate |
|---|---|---|---|
| W1 | Nov 10–16 | Evidence inventory, prior-art matrix, three hypothesis cards | G1: scientific review |
| W2 | Nov 17–23 | Preregistered negative controls, as-of checks, evaluation plan | G2: experiment authorization review |
| W3 | Nov 24–30 | Conditional implementation or NO-GO memo; no implicit execution | G3: controlled evaluation |
| W4 | Dec 1–9 | Independent review, replication plan, decision record | G4: human scientific verdict |

## Non-negotiable controls

1. **Default READ-ONLY.** Documentation and issue tracking do not authorize running model forwards, simulations, training, or GPU/API-consuming workflows.
2. Before any experiment: obtain explicit human approval, unique run ID, compute estimate and cap, immutable preregistration, input provenance, durable outputs, and stop conditions.
3. No access to hospital-identifiable data from public CI or repository workflows. Never commit credentials, patient data, private checkpoints, unpublished results, or internal compute ledgers to this public repository.
4. Do not alter historical branches, scientific decisions, immutable artifacts, or existing model weights.
5. Do not merge/rebase across `main` and `mvp/computer-use`. Keep their histories separate.
6. Do not merge, deploy, or promote a model automatically; only independent review plus explicit human sign-off can authorize promotion.
7. Record negative results; MSE improvement alone does not demonstrate causal or temporal representation learning.

## Evidence schema

Every authorized experiment should contain: `hypothesis_id`, `claim`, `prior_art`, `preregistered_prediction`, `dataset_sha`, `available_at_contract`, `split`, `baseline`, `negative_control`, `seed`, `code_sha`, `run_id`, `authorization_id`, `compute_cap`, `results`, `confidence_interval`, `independent_review`, `verdict`, `timestamp`.

## Decision values

`NOT_TESTED`, `FALSIFIED`, `INDETERMINATE`, `SUPPORTED_SYNTHETIC_ONLY`, `SUPPORTED_EXTERNAL`. Any scientific promotion requires an independent approval step.

## Cycle completion criteria

Three falsifiable hypothesis cards; at least two robust negative controls on paper; one preregistered experimental protocol; a documented evidence inventory with provenance; one independent review; zero unauthorized compute launches.
