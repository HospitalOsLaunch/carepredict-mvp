# HospitalOS Command Center Dashboard

This local Streamlit dashboard presents the Hospital World Model as an
operations command center for scientific and product review. It remains a local
demo surface and does not change the FastAPI or ML runtime.

## Purpose

HospitalOS Command helps reviewers inspect predicted care-load saturation,
staffing pressure, admission peaks, and simulated operational actions across a
48-hour planning horizon.

## Prerequisites

1. Generate artifacts when needed:

```bash
python scripts/train_rssm_synthetic.py --plot
```

2. Start the API:

```bash
uvicorn services.api.main:app --port 8000
```

3. Install presentation-only dependencies if missing:

```bash
pip install "streamlit>=1.35,<2.0" "plotly>=5.18,<6.0"
```

## Launch

```bash
streamlit run dashboards/rssm_demo.py
```

Open `http://localhost:8501`.

## Architecture

```text
Browser
  -> Streamlit HospitalOS Command (port 8501)
      -> FastAPI simulation API (port 8000)
          -> RSSM checkpoint + scaler + conformal residuals
```

## Navigation

- Command Center: service risk cards, propagation view, predictive alerts,
  48h forecast, and operational KPIs.
- Simulation d’impact: compare baseline and recommended intervention plans.
- Prévision 48h: edit SIIPS history and planned actions, then recalculate.
- Diagnostics: expert-mode status, artifacts, model card, and conformal residuals.

## Limitations

- Synthetic SIIPS only.
- Single-service, single-hospital scope at this stage.
- Federated learning designed but not validated.
- No clinical validation; not a medical device.
