# HospitalOS — Synthetic-first full world-model pretraining and autonomous lab

**Date:** 2026-11-10. **Status:** design correction, NOT training authorization. **Target branch:** `research/lab-runtime-2026-11`. **Scope:** Cycle-01 and follow-on private execution. Keep `mvp/computer-use` isolated from `main`.

## 1. Correct scientific objective

The lab's primary goal is to **pretrain a reusable hospital world model on synthetic multi-hospital trajectories**, then assess out-of-generator generalization and, in a separate authorized phase, adapt/validate against as-of-qualified real operational sources. **Absence of real hospital exports must not block synthetic pretraining *design*.** Real-data G0 is a downstream adaptation/transfer gate, not a prerequisite for synthetic model architecture design.

"Full world model" here refers to the **trainable model chain**, not necessarily every piece of the future clinical product:
- observation encoder and JEPA context/target predictor;
- belief/recurrent dynamics (RSSM) with stochastic and deterministic latent, conditioned on **only available action histories**;
- multi-horizon readouts for observable operational quantities and uncertainty;
- optionally, action-effect probes / structured decoder only when the synthetic action support and simulator interventions warrant the claim.
A planner, optimization controller, hospital connectors and computer-use agents are **separate components**. They are not implicitly "pretrained" by training the dynamics model. A causal/action effect or real-world deployability is never established by synthetic predictive fit alone.

## 2. Existing components and gaps (repository source inspection, not a runnable integrated pipeline)

| Layer | Located code | Current limitation |
|---|---|---|
| Multi-site synthetic physics, policies, observational latency and missingness | `src/hospitalos/synthetic/*`, `configs/synthetic/*` | Generator assumptions are synthetic; realism and cross-generator support need qualification |
| As-of/versioned observation boundary | `src/hospitalos/operational/contract.py`, `adapter.py` | Research feed is explicitly `synthetic_only`, not an actual hospital connector |
| JEPA pretraining | `rs_jepa/train.py`, `src/hospitalos/encoders/ts_jepa/jepa_module.py` | Multiple partially distinct stacks; need checkpoint/interface compatibility audit |
| Action-conditioned RSSM | `rs_jepa/rssm.py`, `src/hospitalos/dynamics/jepa_rssm.py`, `services/ml/world_model/rssm.py` | Different RSSM variants; one JEPA-RSSM implementation freezes encoder; no verified single full-stack training recipe |
| Multi-horizon heads | `rs_jepa/train_stage2.py`, `services/ml/world_model/*` | Frozen readout and standalone SIIPS trainer are not a common trainable joint world-model release |
| Evaluations and reference models | `src/hospitalos/operational/experiment.py`, existing synthetic lot reports | Need fixed strong persistence/seasonality/lag baselines, origin-level evidence, OOD splits and action-support checks |
| Research planning agents | `research_lab/cli.py` | Six-stage text-only **one-shot** cycle; no data/code tools, no retrieval, no scheduled loop or experiment executor |
| CI | `.github/workflows/research-lab-guarded.yml` | PR/manual offline pytest only; it does not run research or GPU jobs |
| Daily research follow-up | ChatGPT scheduled automation (external to this repository) | Proactive **read-only** research/reporting from 2026-11-10 08:00 Paris, not a persistent ML executor |

Do not assert that a single full synthetic model is already jointly pretrained, nor that the six-role agent runner autonomously conducts experiments.

## 3. Synthetic-first training work packages (proposed, not executed)

| Package | Output / pass criterion | Negative controls and failure rules |
|---|---|---|
| S0 — Universe/data contract | Train/val/test synthetic hospitals across independent seeds, structures, policies and observation profiles; `event_time`, `available_at`, revisions; frozen manifest | No simulator truth or hidden causes in as-of features; no overlap of origins; no generator-seed leakage |
| S1 — Representation | Self-supervised JEPA encoder under observation masks and delay-aware semantics, collapse diagnostics and frozen replay checkpoint | Strong mean/last/recency/missingness/calendar reference; shuffled-but-supported witness; no promotion for trivial mean-only gains |
| S2 — Latent dynamics | Action-conditioned RSSM and belief state trained on synthetic trajectories; explicit action-time alignment; frozen rollout contract | Action ablations, action permutation under matched support, same history/seed conditions; fail on disallowed future action oracle |
| S3 — Integrated model | Versioned complete checkpoint `encoder + predictor + RSSM + heads`; staged warmup then **conditional** joint fine-tuning with gradient and stability tests | End-to-end gradients checked; no silent encoder freezing; compare to modular frozen stack, ablations and persistence |
| S4 — Forecast and decision utility | H+1/6/24 calibrated predictions, bias, MAE/MSE, intervals, subgroup reports, non-compensating flux checks | Saturated regime and transport/SMR stress; stop on no reproducible gain vs strong baselines |
| S5 — Generalization | Unseen structures, policies, observation latencies, parameter families and seed generators; multiple repetitions | No tuning on held-out generator worlds; if generalization fails, label `SUPPORTED_SYNTHETIC_ONLY` or `INDETERMINATE` correctly |
| S6 — Separate real adaptation proposal | HDS/source as-of qualification, minimal adapter, domain shift plan | Requires separate real-data access, governance and authorization; not an input to S0–S5 design |

Training all modules together **from step zero** is not assumed optimal. A reasonable candidate is staged initialization plus joint fine-tuning of trainable components after ablation, not a promise of superiority.

## 4. Autonomy levels and deployment reality

- **L0 — Monitoring:** scheduled status reporting, no agent initiative. **Prior state of external scheduled task.**
- **L1 — Scientific planning autonomy:** choose one falsifiable next bottleneck, inspect allowed code and public literature, propose tests and adversarial critiques, publish daily. **External task updated and enabled; no runs yet at time of change.**
- **L2 — Code autonomy:** agent authors a bounded change in an isolated branch, runs offline unit/fixture tests, opens a draft PR and seeks review; needs a persistent private tool executor and write authorization. **NOT DEPLOYED.**
- **L3 — Experimental autonomy:** private GPU worker executes only signed, frozen, synthetic-only `run_spec` with explicit resource/time/cost cap and auditable outputs. **NO-GO / NOT DEPLOYED.**
- **L4 — Adaptive scientific loop:** after approved results, agent can propose next run within a pre-approved envelope and an immutable plan/safe search space; no access to reserved holdout for adaptive tuning. **NOT DEPLOYED.**
- **L5 — Promotion/clinical action:** never autonomously; independent evidence and human sign-off.

**Architecture target:** daily research controller -> task queue/state machine -> authorized private executor -> artifact registry with checksums -> independent evaluator -> bounded hypothesis/experiment queue -> human approval for protected gates. A daily chat automation cannot by itself host the executor, run private GPUs, access Mac files or sign model promotion.

## 5. Permission matrix

| Operation | Autonomous now | Needs separate approval/infrastructure |
|---|---|---|
| Public literature review + connected repo reads | Yes, for the scheduled read-only task | No |
| Hypothesis generation, adversarial review, protocol and experiment plan | Yes, documentary | Human sign-off still required for scientific acceptance per charter |
| CI offline fixture tests already defined in repo | CI on PR events, not an autonomous research experiment | No direct new training permission implied |
| Code changes / draft PR from autonomous executor | No | Private execution environment + scoped GitHub permissions, policy tests |
| New synthetic generation / training / model forwards / paid services | **NO** | Frozen run-specific permission or approved research envelope with hard guardrails and verified account controls |
| Read/write real hospital records | **NO** | Institutional governance, HDS/secure source contract and explicit access |
| Merge / deploy / promote | **NO** | Independent evidence, explicit human approval |

The local text runner's `--budget-usd` is a pre-call quote and **not** a hard provider billing cap. Secrets must not be entered into public CI or the repo.

## 6. Required private-executor safety contract (design only)

One immutable `run_spec` per experiment:
- `id`, hypothesis, owner approval ID, approval timestamp, scope=`synthetic_only`, approved commit, allowed scripts/commands hashes, immutable config+data+generator+protocol hashes;
- held-out partition lock, admissible as-of cutoff, seeds, max steps/epochs, GPU-hour cap, dollar cap, timeout, automatic fail-closed and cancellation policy;
- permitted branch prefix, no access to main/product and patient data, disabled network egress except allowlisted providers, no automatic merge/promotion;
- log/artifact destination, status transitions `PROPOSED -> REVIEWED -> APPROVED -> RUNNING -> COMPLETED/FAILED/CANCELLED -> EVALUATED`, journal hashes and exact checkpoint fingerprints;
- isolated evaluator and explicit holdout opening rule; independent challenge/decision.

Never infer consent to spend from "the objective is to pretrain" or from a paper protocol. There is **no synthetic-training run permit yet**.

## 7. Immediate deliverables to build before G2

1. Choose the canonical interfaces between `rs_jepa`, `hospitalos.encoders.ts_jepa`, and `services/ml.world_model`, then define the full model state/checkpoint schema.
2. Create a synthetic data lineage spec with as-of/revision rules, action histories and clean train/dev/test holdout.
3. Define checkpoint compatibility plus **dry-run plan** that hashes configs and outputs a training plan without model import/forward.
4. Provide strong C0/C1 baseline and negative-control preregistration, including N0 identity and action permutation that preserves support where feasible.
5. Define private executor environment and per-run authorizations before enabling L2+.

**Current decision:** `L1_ENABLED_AWAITING_FIRST_RUN`; `L2_NOT_DEPLOYED`; `L3_NO_GO`; `G1_NOT_FROZEN`; `G2_NO_GO`; existing model verdicts unchanged.
