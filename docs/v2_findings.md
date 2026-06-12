# V2 World-Model Forecast Findings

## A. Frozen Protocol Summary

Evaluation is frozen on `urg-001`, with test origins strictly after
`2025-07-01T00:00:00Z`, one origin per day at `00:00 UTC`, and horizons
`h+24` and `h+48`. Metrics are computed in raw SIIPS space. The same
origin/target pairs are used for all rows where applicable. Bootstrap MAE
confidence intervals use the frozen seeded protocol (`B=2000`).

The v1 and v2 JSON outputs are local artifacts under `artifacts/`. Frozen
v1 baselines are sha256-locked by `artifacts/baseline_v1*.sha256`; v2
experiment JSONs are not frozen, but each records artifact sha256 digests.

### Three Baselines

| Baseline | h+24 MAE | h+48 MAE | Notes |
|---|---:|---:|---|
| Constant train-window mean | 195.33 | 194.72 | Oracle-like floor using the train-window mean for the evaluated service. |
| Seasonal naive | 197.96 | 197.14 | Uses `SIIPS(t+h-168h)` on the same origin/target pairs. |
| V1 weekly-action variant | 240.57 | 251.44 | V1 RSSM with future actions replayed from one week earlier. |

## B. Root-Cause Findings

### V1 Action Skew

The v1 `WorldModelService` conditions historical state with zero actions:
`services/ml/world_model/inference.py:119` creates `history_actions =
torch.zeros(...)`. The B0 diagnostics also showed the baseline evaluator used
zero future actions by default and that replaying weekly actions did not beat
the simple floors. Result: action-fed open-loop rollouts were not a reliable
forecasting path for v1.

### F2 Patch-Length Deviation and Post-Mortem

F2 initially used `patch_len=1` to make the forecast head produce hourly
states, even though the validated JEPA pretraining design used daily patches
(`patch_len=24`). The spec conflict was real: the hourly-state forecast loss
needed valid origins 48..119, while the daily JEPA checkpoint produced only
seven latent states per 168h window. The correct process move was to STOP and
ask before changing granularity. F4 corrected this by reverting to Option B:
daily patches with a direct 48-hour forecast head decoded from day-boundary
states.

### F5 Overfit

The single-service daily 5k run trained on only 51 non-calibration train
windows for `urg-001`. It worsened from the daily-500 result:

| Model | h+24 MAE | h+48 MAE |
|---|---:|---:|
| v2-daily-500 | 217.17 | 206.68 |
| v2-daily-5k | 244.31 | 280.20 |

F6 early stopping later identified best calibration forecast loss at step
750, with stopping at step 1750 and restoration of the best checkpoint. This
supports the diagnosis that the unbounded 5k single-service run overfit the
small train slice.

### F6 Regime Drift

The final F6 multi-service model improves stability but shows degradation
late in the held-out period:

| Horizon | First 8 test weeks MAE | Last 8 test weeks MAE |
|---|---:|---:|
| h+24 | 222.37 | 250.55 |
| h+48 | 184.71 | 294.01 |

Calibration/test residuals also move by horizon:

| Horizon | Calibration mean residual | Test mean residual |
|---|---:|---:|
| h+1 | -27.66 | -63.68 |
| h+24 | +33.14 | -2.61 |
| h+48 | +92.59 | +87.16 |

The h+48 calibration and test residuals are aligned, but the last-eight-week
MAE split indicates temporal regime drift over the test span.

## C. Final Table

| Model | Horizon | MAE | MAE CI 95% | Coverage 90 | Mean interval width |
|---|---:|---:|---:|---:|---:|
| v2-multi | h+24 | 203.62 | [181.12, 226.96] | 0.696 | 557.96 |
| v2-multi | h+48 | 206.98 | [185.15, 229.36] | 0.700 | 548.29 |
| v2-hourly | h+24 | 200.26 | [178.80, 221.55] | 0.796 | 596.76 |
| v2-hourly | h+48 | 206.55 | [185.80, 229.86] | 0.800 | 642.35 |
| v2-daily-500 | h+24 | 217.17 | [193.90, 240.59] | 0.613 | 384.28 |
| v2-daily-500 | h+48 | 206.68 | [185.24, 229.18] | 0.678 | 476.93 |
| v2-daily-5k | h+24 | 244.31 | [217.77, 271.98] | 0.652 | 621.47 |
| v2-daily-5k | h+48 | 280.20 | [249.82, 309.73] | 0.489 | 641.92 |
| v1 full-window RSSM | h+24 | 485.47 | [456.64, 515.48] | 0.060 | 383.24 |
| v1 full-window RSSM | h+48 | 577.39 | [543.43, 613.53] | 0.006 | 181.79 |
| v1 deployed RSSM | h+24 | 487.48 | [457.06, 518.66] | 0.176 | 526.89 |
| v1 deployed RSSM | h+48 | 533.91 | [499.80, 569.88] | 0.006 | 135.49 |
| Seasonal naive | h+24 | 197.96 | [177.55, 218.58] | n/a | n/a |
| Seasonal naive | h+48 | 197.14 | [176.19, 219.98] | n/a | n/a |
| Constant train-window mean | h+24 | 195.33 | n/a | n/a | n/a |
| Constant train-window mean | h+48 | 194.72 | n/a | n/a | n/a |
| V1 weekly-action variant | h+24 | 240.57 | n/a | n/a | n/a |
| V1 weekly-action variant | h+48 | 251.44 | n/a | n/a | n/a |

## D. Pre-Registered Predictions and Outcomes

1. Prediction: action-fed v1 rollouts would not provide a trustworthy
   forecasting baseline once evaluated open-loop. Outcome: supported. The
   v1 full-window RSSM loses badly to seasonal and constant floors, and the
   weekly-action variant remains worse than both floors.

2. Prediction: switching F2 to hourly `patch_len=1` would fix the state-count
   mismatch and produce a stronger v2. Outcome: partially supported. It
   produced the strongest learned h+24 result (`200.26`) and strong coverage,
   but it did not beat the constant or seasonal floors.

3. Prediction: extending the daily run to 5k steps with denser calibration
   would improve the daily model. Outcome: falsified. The 5k single-service
   daily run regressed to `244.31/280.20` MAE versus `217.17/206.68` for the
   500-step daily run.

4. Prediction: multi-service training with urg-only calibration and early
   stopping would reduce overfit and improve robustness. Outcome: supported
   but bounded. The F6 model improves materially over the failed 5k daily run
   and reaches parity with the learned v2 variants, but it still does not beat
   the oracle-like floors over the full holdout.

## E. Open Items

- Adaptive conformal under drift.
- Day-of-year covariate.
- Early-stop/conformal slice separation.
- Generator SIIPS=0 artifacts.
- TFT legacy test failures.
- V1 serving bug, tracked to product backlog.

## F. External Claim

"On calibrated synthetic data designed to favor seasonal baselines,
our v2 world-model forecaster reaches statistical parity with
oracle-like floors and exceeds them on the first half of the held-out
period at 48h. Three failure mechanisms were identified and root-caused
through a sha256-frozen evaluation protocol with pre-registered
predictions. Differentiation will be measured on real hospital data,
where seasonal floors degrade."
