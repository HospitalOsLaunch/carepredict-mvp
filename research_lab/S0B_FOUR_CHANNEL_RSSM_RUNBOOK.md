# HospitalOS — S0b / native four-channel RSSM integration

**Date:** 10 November 2026. **Status:** contract & four-action source preflight implemented, **not** numerically forward-tested or trained. **G1 not frozen / G2 NO-GO**.

## What changed

The existing synthetic hospital V0.4.1 simulator makes four **binary decisions per unit** once per day at 09:00. The S0a same-world exporter `research_lab/synthetic_action_export_v041.py` conservatively maps each unit's native decision into four **hourly hospital-level integer counts**:

1. `anticipation_sorties`
2. `lits_supplementaires`
3. `renfort_soignant`
4. `acceleration_aval`

These are **unit counts with a decision requested**, not the amplitude of staff/bed/throughput changes, and not causal effects. They must never be mapped silently onto the **different** Phase-A action channels `staffing_delta` / `discharge_delta`.

- `research_lab/s0b_four_channel_bridge.py` validates the four-channel source receipt and the compatible Stage-1 configuration. It enforces the exact channel order, a complete hourly grid, source clock, availability, 09:00 decision policy, integer counts no larger than the source unit population, and declared source coverage.
- `with_v041_action_dim(stage1)` produces a **new** Stage1Config-compatible dataclass with `action_dim=4`. It does **not** mutate the original two-channel configuration or migrate earlier checkpoints.
- `rs_jepa/integrated_full_model_v041.py` defines a factory that **could instantiate** the existing integrated model modules with an explicit four-channel Stage-1 configuration, but no factory or model forward is called by the dedicated tests.
- `research_lab/synthetic_adapter_v1_files.build_from_archives` now requires an explicit `stage1` for native four-action inputs and emits a `s0b_four_channel_binding` receipt. It still refuses mismatched observed/action manifest hashes and reserved test datasets.

The RSSM remains the existing `rs_jepa.rssm.RSSM`, whose GRU input dimension is derived from `latent_dim + rssm_stoch_dim + action_dim`. For the **fixture config only**, `128 + 32 + 4 = 164`. This is a configuration consistency check, **not** a measured tensor result.

## How to verify safely

On the local checkout of `research/lab-runtime-2026-11`:

```bash
git pull --ff-only
python3 -m research_lab.s0b_four_channel_smoke
python3 -m pytest -q tests/test_s0b_four_channel_bridge.py
```

The CLI smoke uses **only handmade synthetic decision records**. It imports no Torch module, generates no simulated hospitals, performs no forward/backward, consumes no GPU/API budget and never opens a held-out dataset.

## Scientific and operational limitations

- `source_clock = fixed_utc_plus_01_no_dst` is a reference generator clock, **not** Europe/Paris with daylight saving.
- A conservative `available_at = end_of_hour` assumption is part of the synthetic exporter, not evidence for live clinical documentation latency.
- The exporter is an **off-line reader of a preexisting synthetic run**. It does not create new ground-truth episodes or prove the source simulator's causal realism.
- Source manifests and hashes assert that observations and decisions originate in the same existing run; they are not evidence of real hospital equivalence.
- The historical `queue_urgent_hospital` target must not be silently treated as `ed_waiting` from the operational research contract.
- **Future observed labels under the factual policy cannot be treated as no-action counterfactual targets.** The adapter still returns `training_loss_authorized=false`. A future training protocol must distinguish factual future actions, admissible as-of known plans, and separately authorized paired counterfactual synthetic rollouts.
- The four-channel bridge is metadata-only. It has not loaded checkpoints or tested numerical gradients, full-model compatibility under Torch, calibration, decision utility, or physical action effects.
- No GPU executor, automated training schedule, checkpoint promotion, clinical deployment or user spending has been authorized.

## Next true blockers

1. **S0c:** define a *factual future-action training stream* under a pre-registered policy, with explicit masking and leakage exclusions; never feed realized future actions to a production forecast.
2. Align native decisions with **realized intervention executions** if claiming action effects; otherwise retain honest "decision-count" semantics.
3. Under separate G2 authorization, run an isolated minimal **shape / gradient / numerical safety** test before any training.
4. Set synthetic generator family / seed holdouts, baseline scorecards, and train/dev/test non-overlap before large-scale pretraining.
5. Install a persistent private worker with hard provider-side budget controls; the present ChatGPT scheduled task is *L1 research*, not a live autonomous GPU executor.

**Verdict:** `S0B_SOURCE_AND_RSSM_CONTRACT_READY_FOR_REVIEW` / `INTEGRATED_FORWARD_NOT_TESTED` / `TRAINING_NOT_AUTHORIZED`.
