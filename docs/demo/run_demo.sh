#!/bin/bash
# Demo: RSSM Hospital World Model serving
# Usage:
#   bash docs/demo/run_demo.sh
# Pre-requisites:
#   - uvicorn services.api.main:app --port 8000 running in background
#   - artifacts/ populated by `python scripts/train_rssm_synthetic.py`

set -euo pipefail

echo "============================================"
echo "Hospital World Model — Demo Curl"
echo "============================================"
echo ""
echo "POST /simulate/hospital-world"
echo "Payload: 24h history + 3 future action steps"
echo ""

curl -X POST http://localhost:8000/simulate/hospital-world \
  -H "Content-Type: application/json" \
  -d @docs/demo/sample_payload.json \
  -s | python -m json.tool

echo ""
echo "============================================"
echo "Done. See model_version + results above."
echo "============================================"
