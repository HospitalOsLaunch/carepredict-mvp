# integrated_full_model_v1 — interface contract and checkpoint contract

**10 November 2026. Status: assembled source code, not trained, not executed for prediction.**
Research branch: \`research/lab-runtime-2026-11\`. No merge, ML forward or GPU run implied.
**G1: NOT FROZEN. G2: NO-GO.**

## 1. Scope and existing code reuse

This is an **integrated torch module definition**, not another research-agent conversation, a training run or proof that one coherent pretrained HFWM exists.

It reuses the existing \`rs_jepa\` components:

| Component key | Implementation | Purpose |
|---|---|---|
| \`encoder\` | \`rs_jepa.encoder.ObservableEncoder\` | Observed \`[B,C,n_obs]\` to latent \`[B,C,Z]\` |
| \`target_encoder\` | \`rs_jepa.ema.EMATargetEncoder\` | Frozen/EMA JEPA training target, not used in forecasting |
| \`rssm\` | \`rs_jepa.rssm.RSSM\` | Prior-only rollout under specified actions |
| \`jepa_predictor\` | \`rs_jepa.predictor.LatentPredictor\` | \`[B,H,D+S]\` to future latent \`[B,H,Z]\` |
| \`forecast_head\` | NEW \`MultiHorizonGaussianHead\` | Target means and strictly positive scales |

The model outputs \`means\` and \`scales\` shaped \`[B,3,n_targets]\` at **H+1, H+6 and H+24** in the fixture contract. The scale is **uncalibrated heteroscedastic uncertainty**, not conformal uncertainty, clinical confidence, a survival model, epistemic uncertainty, or a guarantee of coverage.

**Important source mismatch:** Stage-1 \`rs_jepa.synthetic.ACTION_COLUMNS\` are precisely \`(staffing_delta, discharge_delta)\`, not generic SIH action types. The v1 contract pins this action order. The operational research schema \`OPERATIONAL_V2_RESEARCH_1\` has hospital observations (including \`ed_waiting\`) but does **not** itself supply this two-channel Stage-1 action history. A **new explicit, audited synthetic adapter** must construct a compatible, as-of-correct training dataset before any model test or training. The bundled spec is a fixture proposal, NOT evidence that the adapter exists.

The historical \`queue_urgent_hospital\` and operational \`ed_waiting\` are **not automatically equivalent**. Only an explicit signed target dictionary can align them. The Stage-1 synthetic generator's \`criticality\` is a privileged diagnostic and must never be silently exposed as an observation.

## 2. Source and input contract

Metadata schema: \`research_lab.integrated_full_model_v1_contract.MODEL_SCHEMA\`.

- \`synthetic_only=true\`; source interface \`OPERATIONAL_V2_RESEARCH_1\` is the proposed canonical adapter output (not yet implemented).
- Fixed context length \`history_steps\`, \`step_hours\`, sorted distinct \`horizons_hours\`.
- Explicit ordered \`observation_features\` including a **missingness mask**, plus \`static_features\` and the action-channel order.
- Every output target specifies \`name\`, **physical unit**, **entity level**, and semantic definition. Avoid blind target-name substitutions.
- Versioned availability is required upstream, \`asof_contract=VERSIONED_AVAILABLE_AT_PER_SOURCE\`.

At prediction time, the module requires:
\`x[B,C,F]\`, \`actions_context[B,C,A]\`, optional \`static[B,S]\`,
\`event_ns[B,C]\`, \`available_ns[B,C]\`, \`origin_ns[B]\` in UTC nanoseconds.

All context observations must satisfy \`event_ns <= available_ns <= origin_ns\`. The array \`available_ns[B,C]\` is **the maximum availability time across all features actually used in that time slice**. Its correctness can only be proven by an upstream version-aware adapter. The model cannot recover a deleted/overwritten source revision from an already materialized tensor.

\`action_mode\` MUST be one of:
- \`no_op\`: no future action tensor, an explicit counterfactual no-action scenario (not a factual forecast under unknown actions).
- \`known_plan\`: specified future actions and their per-horizon version availability at or before \`origin_ns\`; not future realized actions.
- \`counterfactual\`: explicitly hypothetical future action schedule, never reported as factual forecast.

Every action scenario is separate; changing action channels is not a measured causal effect. No observed intervention is treated as an identified treatment without support and confounding checks.

## 3. Model and checkpoint details

Implementation: \`rs_jepa/integrated_full_model_v1.py\`.
Wire/validation: \`research_lab/integrated_full_model_v1_contract.py\`.

New format:
\`\`\`
<private-checkpoint-directory>/
  spec.json               # strict model interface and physical targets
  weights.safetensors     # safe tensor serialization; no pickle execution
  manifest.json           # hashes, source commit, component set and status
\`\`\`

The manifest always lists the five required components. The only writer included in this PR is \`save_untrained_assembly\`; it labels the assembled weights \`UNTRAINED_ASSEMBLY\` with \`global_step=0\` and empty scientific evidence. The only reader included is \`load_untrained_assembly\` and it **refuses trained checkpoints**. The contract validator supports future scientific statuses, but a trained-checkpoint writer/reader needs a separate G2-reviewed implementation.

The existing Stage-1 historical \`encoder_state_dict\` / \`rssm_state_dict\` / \`predictor_state_dict\` files must **not** be relabeled as integrated checkpoints: they lack a common head, signed provenance and guaranteed EMA target state. Existing \`.pt\` loaders may use pickle deserialization; do not open untrusted artifacts for a blind conversion. No checkpoint migration is performed here.

\`inspect_checkpoint\` **never imports torch or reads tensor semantics**; it only checks exact manifest shape, metadata constraints and SHA-256 integrity. A syntactically valid file with fake fixture bytes can pass *metadata* inspection; it **cannot** be loaded as a valid safetensors file. The receipt says \`METADATA_HASHES_VERIFIED_NOT_MODEL_VALIDATED\`, not \`MODEL_VALIDATED\`.

## 4. Zero-training, zero-forward tests

On the checked-out lab branch:

\`\`\`bash
python3 -m research_lab.integrated_full_model_v1_smoke
python3 -m pytest -q tests/test_integrated_full_model_v1.py
\`\`\`

The dedicated \`research-lab-guarded\` workflow runs the tests using only stdlib plus pytest; it must **not** install torch, open weights or run the new forward path.

Checks cover strict source/feature/target/horizon contract, action-dimension alignment, checkpoint metadata hashes, tampering, rejection of inconsistent scientific statuses, and source AST structure, without importing the Torch module. These tests are **control-plane smoke**, not evidence of successful numerical model assembly or forecasting.

## 5. Next milestone before a G2 request

1. Implement and audit **synthetic adapter v1** from multi-hospital observation deliveries to \`[B,C,F]\`, synthetic action histories, versioned as-of time matrices, physical targets and split manifests. Its generated dataset must not expose simulator truth/latent outcomes in input features.
2. Use a *separately approved* isolated runtime to execute a minimal numerical shape/gradient test for the assembled model (including head), then a tiny bounded synthetic training run. No current authorization is implied.
3. Define joint JEPA/RSSM/head losses and EMA schedule, gradient-flow controls, uncertainty calibration procedure, checkpoint resume/optimizer/normalization semantics.
4. Freeze train/val/test world families, independent seeds, OOD mechanisms, strong baselines and negative controls. Do not consult reserved test until approved.
5. Register \`integrated_full_model_v1\` as a training runner **only after** source/data, compute envelope and scientific gates pass. It is not in the worker's current allowlist.

**Decision:** integrated module source + versioned contract now exists; trained complete world model does NOT exist. \`G2=NO_GO\`.
