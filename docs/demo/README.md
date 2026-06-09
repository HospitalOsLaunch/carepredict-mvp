# Hospital World Model — Demo

End-to-end serving demo of the RSSM-based Hospital World Model.

## Prerequisites

1. Trained artifacts in `artifacts/` directory:

```bash
   python scripts/train_rssm_synthetic.py --steps 500 --plot --output-dir artifacts
```

2. API server running:

```bash
   uvicorn services.api.main:app --port 8000 &
```

## Run the demo

```bash
bash docs/demo/run_demo.sh
```

## Expected output

A 200 response with `model_version: rssm-synthetic-v1` and 3 simulation
steps, each containing:

- `predicted_siips` (float): RSSM median forecast
- `lower_bound`, `upper_bound` (float): split-conformal 90% interval
- `reward` (float): predicted reward for the action step
- `is_critical` (bool): true when predicted_siips >= service-level p95

The model demonstrates causal dynamics: discharge-heavy action steps
lower predicted SIIPS, surgery+admission-heavy steps raise it.

## Architecture

- Training: `scripts/train_rssm_synthetic.py`
- Model: `services/ml/world_model/rssm.py` (DreamerV3-style RSSM)
- Serving: `services/api/routers/simulate.py`
- Conformal calibration: `artifacts/conformal_residuals.npz`

Training curves: `artifacts/training_curves.png`.
Scientific memo: `docs/inria_memo.md` (separate document).
