# HFWM-R0 M2B — tableau comparatif

| Bras | Statut | NMAE primaire [IC95] | Couverture 90% | Dérive | CPU total (s) | Latence/épisode (ms) | Décision |
|---|---:|---:|---:|---:|---:|---:|---|
| mechanistic_queue_semimarkov | EXECUTED | 1.529963 [1.153847, 1.983113] | 1.0000 | 1.4899 | 0.0591 | 0.3914 | RETAIN_AS_CONTROL |
| local_joint_from_scratch | EXECUTED | 0.518021 [0.445883, 0.586593] | 0.9583 | 1.0418 | 0.0813 | 0.5385 | RETAIN_AS_CONTROL |
| shared_hfwm_multitask | EXECUTED | 0.552265 [0.458862, 0.635936] | 0.9444 | 1.0500 | 0.0778 | 0.5157 | REJECT_SHARED_CANDIDATE_FOR_M2 |
| hgbr_cqr | EXECUTED | 0.543555 [0.475920, 0.618783] | 0.9306 | 1.0650 | 52.3267 | 252.9870 | ELIGIBLE_FROZEN_FINAL_COMPARATOR |

## Décision primaire

```json
{
  "decision": "REJECT_SHARED_CANDIDATE_FOR_M2",
  "directionally_stable_seed_count": 0,
  "per_target_regression": {
    "inflow": -0.014862970358112966,
    "occupancy": 0.17307578440112872
  },
  "shared_relative_gain_by_seed": {
    "1729": -0.06610563433060707,
    "2718": -0.06610563433060707,
    "3141": -0.06610563433060707
  },
  "shared_relative_gain_ci95_paired_episode_bootstrap": [
    -0.16535572726903944,
    0.033073177711690244
  ],
  "shared_relative_gain_mean": -0.06448868574110046,
  "status": "EXECUTED",
  "strongest_primary_control": "local_joint_from_scratch",
  "thresholds": {
    "directionally_stable_seeds_min": 3,
    "paired_ci_lower_strictly_positive": true,
    "per_target_regression_max": 0.05,
    "relative_gain_min": 0.05
  }
}
```

Statut terminal : `HFWM_R0_CANDIDATE_KILLED`

Portée : données synthétiques rétrospectives, shadow only, aucun site réel.
