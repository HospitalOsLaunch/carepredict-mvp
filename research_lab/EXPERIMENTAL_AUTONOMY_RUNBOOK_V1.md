# HospitalOS — Experimental autonomy worker v0.1

**2026-11-10. Status: control-plane prototype / bounded offline execution. NOT a full autonomous model-training lab.**
**G1 full-model training protocol: NOT FROZEN. G2: NO-GO. Model promotion: never autonomous.**

This is a **real, testable queue runner** with a strict synthetic-only command allowlist, signed human permits, fixed source/configuration hashes, exclusive worker lock, tamper-evident event journal, halt-on-error semantics and wall-clock/iteration bounds. It currently runs one safe metadata fixture without permits; its sole optional ML adapter invokes the **existing RS-JEPA Stage 1** trainer under explicit permission. It does **not** yet train JEPA + RSSM + all forecast/uncertainty heads as one integrated model, nor does it select the next experiment with an LLM or manage GPUs.

## Immediately runnable: a safe queue test

On a checked-out repository branch with Python 3.11+:

\`\`\`bash
python3 -m research_lab.queue_smoke
python3 -m pytest -q tests/test_experimental_autonomy.py
\`\`\`

Expected signature: \`PASS_OFFLINE_QUEUE_SMOKE\`, one job, two validated events, \`model_forward: false\`, no simulation or GPU/API cost. The workspace is an isolated temporary folder and is deleted on exit. This is **software smoke**, not scientific evidence.

## Experimental control-plane interface

\`\`\`bash
python3 -m research_lab.experimental_autonomy inspect \
  --repo . --queue /PRIVATE/queue --workspace /PRIVATE/results

python3 -m research_lab.experimental_autonomy tick \
  --repo . --queue /PRIVATE/queue --workspace /PRIVATE/results

python3 -m research_lab.experimental_autonomy loop \
  --repo . --queue /PRIVATE/queue --workspace /PRIVATE/results --max-jobs 10
\`\`\`

These commands do not enable ML by default. Jobs are immutable \`run_id.json\` files with the exact schema required by \`experimental_autonomy.validate\`:

\`\`\`json
{
  "schema": "hospitalos.synthetic-experiment.v1",
  "run_id": "trial-syn-001",
  "runner": "offline_manifest_verify",
  "source_commit": "0000000000000000000000000000000000000000",
  "config_path": "configs/phaseA.yaml",
  "config_sha256": "REPLACE_WITH_VERIFIED_64_CHARACTER_SHA256",
  "synthetic_only": true,
  "limits": {
    "wall_seconds": 600,
    "max_epochs": 1,
    "steps_per_epoch": 1,
    "max_gpu_count": 1
  }
}
\`\`\`

This template is **illustrative and intentionally invalid** until the SHA is replaced. \`offline_manifest_verify\` only checks the existence and SHA of a repository configuration. All jobs are auditable; each completed \`run_id\` is not executed twice. A crash between STARTED and FINISHED causes a **manual-review halt**, not an automatic retry. The worker takes a nonblocking exclusive file lock and halts on the first invalid job or failed run.

## Future authorized Stage-1 experiments only (not enabled by this change)

\`runner: "rs_jepa_stage1"\` may execute the existing \`rs_jepa.cli --stage 1\` under **all** of these conditions:

1. A **separate** explicit authorization for the exact \`run_id\`, approved source commit, synthetic configuration SHA and wall-time/epoch/step bounds.
2. Operator signs the **exact JSON bytes** with a private RSA key stored **outside the worker**, using a command equivalent to \`openssl dgst -sha256 -sign operator_private.pem -out /PRIVATE/approvals/<run_id>.sig /PRIVATE/queue/<run_id>.json\`. Keep the key and signatures private.
3. The worker is provisioned with only the public key, and an operator-pinned environment value \`HOS_LAB_TRUSTED_PUBKEY_SHA256\`; absence or mismatch causes refusal.
4. Training is invoked with the explicit \`--allow-training\` option, a real isolated synthetic-only worker, and \`HOS_LAB_PRIVATE_SANDBOX=synthetic-only-v1\` set *by that worker's trusted launcher*. This environment flag alone is **not** security isolation or proof of confidential-data protection.
5. The Git checkout has the exact commit specified in the signed permit and no tracked modifications. The requested CLI is constructed from a fixed allowlist; no arbitrary shell strings, scripts, or file paths from model output are executed.
6. An **external** compute provider must enforce account/resource spend caps, network egress restrictions, GPU allocation, storage ACLs, and emergency cancellation. \`wall_seconds\` and CLI iteration bounds are not hard financial limits.

**Do not invoke authorized-training mode until G2 grants a bounded run permit and the secure worker exists.** This documentation does not authorize any experiment. The example plan above uses a zero hash intentionally and cannot be treated as a signed model run.

## Where the autonomous laboratory still stops

- **L1 / research:** daily scientific task can inspect the approved GitHub repo and propose hypotheses, but cannot currently write a private run queue or control GPUs.
- **Control plane:** implemented on draft PR #46; verified only on fixture tests. Its \`loop\` executes a fixed ordered queue of already approved jobs, **not** adaptive experiment design.
- **L2 / code worker:** not deployed; requires private sandbox, scoped GitHub bot permissions, code review, artifact destination and branch isolation.
- **L3 / full-model trainer:** not deployed. Need a reviewed integrated runner checkpointing the **encoder + JEPA predictor + action-conditioned RSSM + multi-horizon heads and uncertainty**, strong C0/C1 controls, and train/dev/test isolation.
- **L4 / adaptive research:** not deployed. Later, allow a bounded policy to propose variants and collect results without using reserved test data adaptively; approval must be signed for the whole bounded search envelope or each exact job.
- **L5 / scientific promotion / clinical deployment:** must remain human-governed.

Avoid commingling \`mvp/computer-use\` and \`main\` histories or publishing proprietary histories, checkpoints or patient data.

**Operational readiness decision: \`SIGNED_EXPERIMENT_CONTROL_PROTOTYPE\`; \`FULL_SYNTHETIC_PRETRAINING_NOT_AVAILABLE\`; \`G2_NO_GO\`.**
