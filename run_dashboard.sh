#!/bin/bash
# Launch the Hospitalos dashboard with proper PYTHONPATH

set -euo pipefail

# Ensure venv is active
if [ -z "${VIRTUAL_ENV:-}" ]; then
    source .venv/bin/activate
fi

# Check API is running
if ! lsof -i :8000 > /dev/null 2>&1; then
    echo "Warning: FastAPI not running on :8000"
    echo "Start it with: uvicorn services.api.main:app --port 8000 &"
fi

# Launch Streamlit from project root
PYTHONPATH=. streamlit run dashboards/rssm_demo.py
