#!/usr/bin/env bash
set -euo pipefail

# Explicit local-only API access; never paste the key into GitHub or this chat.
if [[ "${1:-}" != "--live" ]]; then
  echo "Usage: bash research_lab/launch-mac.sh --live"
  echo "Requires an API key and may incur up to the locally estimated budget."
  exit 2
fi
if [[ ! -f "research_lab/mandate-cycle-01.txt" ]]; then
  echo "Run from the repository root." >&2
  exit 2
fi

VENV="$HOME/.venvs/hospitalos-research-lab"
mkdir -p "$HOME/.venvs"
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --disable-pip-version-check 'openai>=2,<4' 'pytest>=8,<10'
"$VENV/bin/python" -m pytest -q tests/test_research_lab.py

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  printf 'OpenAI API key (input hidden): '
  IFS= read -r -s OPENAI_API_KEY
  printf '\n'
  export OPENAI_API_KEY
fi
trap 'unset OPENAI_API_KEY' EXIT
if [[ -z "$OPENAI_API_KEY" ]]; then
  echo "No key supplied, refusing." >&2
  exit 2
fi

# Preflight only: confirm account can see both required model IDs.
"$VENV/bin/python" - <<'PY'
from openai import OpenAI
client = OpenAI(max_retries=0, timeout=30)
for model in ('gpt-6-astra', 'gpt-6.1-sol'):
    try:
        client.models.retrieve(model)
    except Exception as exc:
        raise SystemExit(f"Model access not verified for {model}: {type(exc).__name__}")
print("Model IDs accessible. This alone does not guarantee the live request succeeds.")
PY

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
WORKSPACE=".research-lab-live-${RUN_ID}"
echo "Launching six-stage text-only cycle into $WORKSPACE"
"$VENV/bin/python" -m research_lab run \
  --mode live --allow-api --budget-usd 1.00 \
  --brief research_lab/mandate-cycle-01.txt \
  --workspace "$WORKSPACE"
"$VENV/bin/python" -m research_lab status --workspace "$WORKSPACE"
echo "Private results remain locally in: $WORKSPACE"
