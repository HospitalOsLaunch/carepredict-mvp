# HospitalOS / CarePredict MVP

HospitalOS is building a hospital operations world model: an AI system that learns how hospital pressure evolves across care workload, staffing, beds, patient flow, and capacity.

The current MVP, CarePredict, validates the first wedge of this vision by forecasting nursing workload from SIIPS-style operational time series. It includes a synthetic-data pipeline, FastAPI serving layer, and a v2 forecasting stack combining a TS-JEPA encoder, RSSM dynamics, and direct multi-horizon prediction.

This architecture is designed to move beyond dashboards and static forecasting. The long-term goal is to create a predictive and simulation-based operating layer for hospitals: a system that can anticipate future bottlenecks, explain the drivers of pressure, simulate resource decisions, and recommend the best actions across staff, beds, and care operations.

CarePredict is therefore not the final product, but the technical foundation of HospitalOS: a step toward AI-native hospital resource orchestration.


This README is written for technical and due-diligence reviewers. It explains
what is in the repo, how to run the main paths, and where the authoritative
measurement artifacts live.

## What To Review First

### Non-Technical Reviewer

- `docs/v2_findings.md` - concise findings, caveats, and external claim.
- `docs/demo/README.md` - small RSSM serving demo and expected response shape.
- `dashboards/README.md` - local Streamlit dashboard scope and launch notes.
- `artifacts/baseline_v1_full.json` - frozen baseline result artifact.
- `README.md` - repository map and reproduction commands.

### Technical Reviewer

- `src/hospitalos/dynamics/jepa_rssm.py` - JEPA-conditioned RSSM and forecast
  head.
- `src/hospitalos/training/train_v2_forecast.py` - v2 training, calibration,
  and early stopping.
- `src/hospitalos/eval/eval_v2.py` - frozen-protocol v2 evaluation.
- `src/hospitalos/data/timescale_adapter.py` - canonical TimescaleDB to
  JEPA/RSSM tensor contract.
- `tests/test_eval_v2.py` and `tests/test_forecast_head.py` - protocol and
  leakage guards.

## Current Status

### Running Now

- FastAPI service is under `services/api/` and includes health, prediction,
  and simulation routers from `services/api/main.py`.
- The legacy `/predict/charge` path remains in `services/api/routers/predict.py`
  and uses the TFT-facing dependencies under `services/api/dependencies/`.
- The RSSM simulation endpoint is exposed through
  `services/api/routers/simulate.py` as `POST /simulate/hospital-world`.
- Canonical synthetic data can be generated into TimescaleDB through
  `data/synthetic/siips_generator.py`.
- The v2 Timescale training/evaluation path is under `src/hospitalos/`.
- The local Streamlit dashboard is WIP under `dashboards/`; its unit tests pass,
  but this README does not treat it as a production surface.

### Frozen

- `artifacts/baseline_v1.json` and `artifacts/baseline_v1.sha256` freeze the
  deployed v1 baseline.
- `artifacts/baseline_v1_full.json` and `artifacts/baseline_v1_full.sha256`
  freeze the full-train-window v1 comparator.
- Immutability tests live in `tests/test_baseline_frozen.py` and
  `tests/test_baseline_full_frozen.py`.
- `docs/v2_findings.md` is the source of truth for measured v2 outcomes and
  should be linked, not duplicated.

### In Progress

- `410a34d feat(dashboard): WIP dashboard pages and tests` adds dashboard
  glossary, microcopy, help/sidebar code, and unit tests.
- `b53a1dd docs(ml): close v2 forecast findings` adds the findings document
  and fixes the v2 eval console label.
- `258d7f0 feat(ml): train v2 forecast with multi-service early stopping`
  adds the F6 multi-service/early-stopping training path.

### Out Of Scope Here

Open research and hygiene items are tracked in `docs/v2_findings.md`, section
`E. Open Items`. This README intentionally does not expand that backlog.

## Repository Layout

```text
.
├── artifacts/              Frozen baseline JSONs and local ML artifacts.
├── dashboards/             WIP Streamlit dashboard and dashboard helpers.
├── data/                   Synthetic SIIPS generator and generated CSV output.
├── docs/                   Findings and demo documentation.
├── infrastructure/         Docker images/config for API, Dagster, Feast,
│                           MLflow, Redpanda, and TimescaleDB.
├── orchestration/          Dagster workspace/assets.
├── scripts/                Standalone RSSM synthetic training script.
├── services/               FastAPI, connector, dashboard, feature pipeline,
│                           legacy ML, and validation services.
├── src/hospitalos/         TS-JEPA, RSSM, Timescale adapter, v2 training,
│                           diagnostics, and evaluation code.
├── tests/                  Unit, integration, and e2e tests.
└── runs/                   Local smoke/pretraining/diagnostic outputs.
```

Selected first-level package layout:

```text
src/hospitalos/data/        Synthetic and Timescale dataset adapters.
src/hospitalos/dynamics/    JEPA-conditioned RSSM and forecast head.
src/hospitalos/encoders/    TS-JEPA patcher, encoder, predictor, probes.
src/hospitalos/eval/        Baseline and v2 evaluation/diagnostic scripts.
src/hospitalos/training/    JEPA, RSSM, smoke, and v2 forecast training.

services/api/               FastAPI application, routers, schemas, dependencies.
services/ml/world_model/    Earlier standalone RSSM service implementation.
services/ml/models/         Legacy TFT/Moirai wrappers and tests.
services/feature_pipeline/  dbt and Feast feature pipeline assets.
services/dashboard/         Vite dashboard from the earlier app surface.

infrastructure/timescaledb/ TimescaleDB init SQL.
infrastructure/redpanda/    Redpanda topic config.
infrastructure/dagster/     Dagster Docker/runtime config.
infrastructure/mlflow/      MLflow Docker/runtime config.
```

## Stack

The project targets Python 3.11 (`.python-version`, `pyproject.toml`) and uses
the following components that are present in tracked code or configuration:

- ML/runtime: `torch`, `lightning`, `numpy`, `pandas`.
- API/contracts: `fastapi`, `pydantic`, `uvicorn`, `structlog`.
- Database access: `psycopg`, `psycopg2`, TimescaleDB/Postgres.
- Feature/data platform: `dbt-core`, `dbt-postgres`, `dagster`,
  `dagster-dbt`, `feast[redis,postgres]`.
- Experiment tracking and calibration: `mlflow`, `mapie`, `properscoring`.
- Legacy forecasting stack: `pytorch-forecasting`, `uni2ts`.
- Docker services from `docker-compose.yml`: Redpanda, TimescaleDB, Redis,
  Dagster Postgres, Dagster webserver/daemon, MLflow, API, and Vite dashboard.

CI is configured in `.github/workflows/ci.yml` for linting, type checking,
tests, Docker Compose config, and Docker build.

## Getting Started

Prerequisites:

- Docker with Compose support.
- Python 3.11.
- A virtual environment with the project installed, for local CLI/test runs.

Create local environment values:

```bash
cp .env.example .env
```

Start local services:

```bash
docker compose up -d
docker compose ps
```

Wait for healthchecks before running DB-backed commands. The default local
database credentials are development credentials already present in
`.env.example` and `docker-compose.yml`.

Seed synthetic canonical data into TimescaleDB:

```bash
PYTHONPATH=. python -m data.synthetic.siips_generator --output-format db --seed 42
```

Run a Timescale-backed TS-JEPA smoke train:

```bash
PYTHONPATH=src python -m hospitalos.training.smoke_jepa_timescale \
  --steps 100 \
  --batch-size 16 \
  --seed 0 \
  --train-end 2025-07-01 \
  --out runs/smoke_timescale
```

Run the default test suite:

```bash
PYTHONPATH=src pytest -q
```

`pyproject.toml` skips tests marked `integration` by default. To include
external-service tests explicitly:

```bash
PYTHONPATH=src pytest -q -m "integration or not integration"
```

## Architecture Overview

The v2 path uses a two-stage design. A TS-JEPA encoder learns compact temporal
representations from canonical hospital time series. A JEPA-conditioned RSSM
then models latent dynamics and a direct forecast head predicts SIIPS horizons
from posterior states. The measurement record and failure analysis are in
`docs/v2_findings.md`; this README does not restate those result tables.

The Timescale adapter maps canonical hourly data to model inputs through
`src/hospitalos/data/timescale_adapter.py`. The current channel contract is
explicit there and excludes `siips_score` from the input series; SIIPS remains
the target.

## Training and Evaluation Entrypoints

| Command | Purpose | Artifact produced |
|---|---|---|
| `python scripts/train_rssm_synthetic.py` | Train the standalone CarePredict RSSM on synthetic SIIPS data. | `rssm_checkpoint.pt`, `siips_scaler.npz`, `conformal_residuals.npz` under `--output-dir`. |
| `PYTHONPATH=src python -m hospitalos.training.pretrain_jepa` | Pretrain a TS-JEPA encoder when a maintainer wires a dataset. | Encoder/patcher checkpoint at `--out`. |
| `PYTHONPATH=src python -m hospitalos.training.smoke_jepa` | Run a synthetic TS-JEPA smoke train. | `runs/smoke/encoder_smoke.pt`. |
| `PYTHONPATH=src python -m hospitalos.training.smoke_jepa_timescale` | Run a canonical Timescale TS-JEPA smoke train. | `runs/smoke_timescale/encoder_smoke_timescale.pt` by default. |
| `PYTHONPATH=src python -m hospitalos.training.train_rssm` | Train a JEPA-conditioned RSSM from an encoder checkpoint. | RSSM checkpoint at `--out`. |
| `PYTHONPATH=src python -m hospitalos.training.train_v2_forecast` | Train the v2 direct RSSM SIIPS forecast head. | `checkpoint.pt`, `conformal_q.npz`, `train_config.json` under `--out`. |
| `PYTHONPATH=src python -m hospitalos.eval.baseline_v1` | Evaluate the frozen v1 RSSM baseline. | Baseline JSON at `--out`. |
| `PYTHONPATH=src python -m hospitalos.eval.diagnose_v1` | Diagnose v1 full-window RSSM behavior. | Diagnostic text/JSON under `runs/diagnose_v1/`. |
| `PYTHONPATH=src python -m hospitalos.eval.diagnose_f5c` | Diagnose daily v2 origin-index alignment. | Console JSON report. |
| `PYTHONPATH=src python -m hospitalos.eval.eval_v2` | Evaluate a v2 direct forecast artifact on the frozen protocol. | `eval_v2.json` under the selected artifact directory. |

## Frozen Baselines and Artifacts

The baseline JSON files are committed even though `artifacts/` is ignored in
`.gitignore`. They were force-added so reviewers can verify the frozen
protocol without regenerating those results.

Tracked frozen baseline files:

- `artifacts/baseline_v1.json`
- `artifacts/baseline_v1.sha256`
- `artifacts/baseline_v1_full.json`
- `artifacts/baseline_v1_full.sha256`
- `artifacts/v1_full/rssm_checkpoint.pt`
- `artifacts/v1_full/siips_scaler.npz`
- `artifacts/v1_full/conformal_residuals.npz`

Immutability tests:

- `tests/test_baseline_frozen.py`
- `tests/test_baseline_full_frozen.py`

Current v2 experiment artifacts are also present locally under
`artifacts/v2_forecast*`, but the authoritative interpretation is
`docs/v2_findings.md`.

## API and Dashboard

FastAPI is the maintained serving boundary in this repo. Start it locally with
`uvicorn services.api.main:app --port 8000` or through Docker Compose. The
dashboard under `dashboards/` is WIP local-demo code from commit `410a34d`;
its unit tests pass, but it should be treated as a review aid rather than a
validated product UI.

## Development Discipline

The v2 work used fenced commits, pre-registered predictions, and
sha256-frozen baseline JSONs for the evaluation protocol. Anti-collapse
probes are implemented for TS-JEPA under `src/hospitalos/encoders/ts_jepa/`.
Several diagnostic scripts are intentionally retained so a reviewer can trace
the decision path instead of only seeing the final artifact.

## Known Caveats

- V1 serving/action behavior is a known issue; the RSSM service initializes
  historical actions as zeros in `services/ml/world_model/inference.py:119`.
- TFT legacy tests are still recorded as an open item in `docs/v2_findings.md`.
- The canonical DB used during this review contains 52 `siips_score <= 0`
  rows in `canonical.care_load`; model/eval adapters exclude non-positive
  SIIPS windows or targets.
- `runs/` is not fully ignored. `.gitignore` ignores `runs/smoke/`, but other
  `runs/*` outputs can remain untracked unless handled separately.
- Adaptive conformal under drift, day-of-year covariates, and stricter
  early-stop/conformal split separation are open research/hygiene items in
  `docs/v2_findings.md`.

## License and Contact

License: TODO. No tracked license file is present in this checkout.

Contact: TODO. Add the repository owner or project contact before sharing
outside the private review group.
