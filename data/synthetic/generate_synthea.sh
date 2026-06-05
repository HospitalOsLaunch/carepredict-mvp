#!/usr/bin/env bash
set -euo pipefail

PATIENT_COUNT="${SYNTHETIC_PATIENT_COUNT:-1000}"
MONTHS="${SYNTHETIC_MONTHS:-24}"
OUTPUT_DIR="${SYNTHETIC_OUTPUT_DIR:-data/generated/synthea}"

mkdir -p "${OUTPUT_DIR}"
echo "Synthea generation placeholder: patients=${PATIENT_COUNT} months=${MONTHS} output=${OUTPUT_DIR}"
echo "Full Synthea download and generation is implemented in pass 1 step 2."
