# Hospitalos predictive dashboard

This local Streamlit dashboard presents the RSSM Hospital World Model as a
French operational review surface. It is a local demo interface only and does
not change the FastAPI or ML runtime.

## Purpose

The dashboard helps technical reviewers inspect predicted nursing workload,
compare operational action plans, and review model diagnostics over a 48-hour
planning horizon.

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
  -> Streamlit Hospitalos dashboard (port 8501)
      -> FastAPI simulation API (port 8000)
          -> RSSM checkpoint + scaler + conformal residuals
```

## Navigation

- Prévision 48h: hero tab with French-labeled inputs, synthesis, forecast
  chart, KPI cards, and per-hour details.
- Simulation what-if: compare Plan A and Plan B with French action labels.
- Vue exécutive: factual synthesis derived from the latest prediction; this
  replaces the previous Command Center view and removes invented service data.
- Diagnostics modèle: model card, conformal residuals, limitations, and
  reproducibility commands.

## Limitations

- Modèle entraîné uniquement sur données synthétiques.
- Périmètre actuel : un service, un établissement.
- Federated learning conçu mais non validé empiriquement.
- Sans validation clinique : non utilisable comme dispositif médical.
