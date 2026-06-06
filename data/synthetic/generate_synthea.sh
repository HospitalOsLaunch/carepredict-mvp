#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GENERATED_DIR="${ROOT_DIR}/data/generated"
SYNTHEA_DIR="${GENERATED_DIR}/synthea"
BIN_DIR="${GENERATED_DIR}/bin"
CONFIG_DIR="${GENERATED_DIR}/synthea-config"
PATIENT_COUNT="${SYNTHETIC_PATIENT_COUNT:-1000}"
MONTHS="${SYNTHETIC_MONTHS:-24}"
SEED="${SYNTHEA_SEED:-20260606}"
RELEASE_TAG="${SYNTHEA_RELEASE_TAG:-}"
JAR_PATH="${BIN_DIR}/synthea-with-dependencies.jar"
GITHUB_RELEASES_URL="https://github.com/synthetichealth/synthea/releases"

log() {
  printf '[synthea] %s\n' "$*"
}

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    log "commande requise introuvable: ${command_name}"
    exit 1
  fi
}

download_with_curl_or_wget() {
  local url="$1"
  local output="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --retry 3 --output "${output}" "${url}"
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    wget --tries=3 --output-document="${output}" "${url}"
    return
  fi
  log "curl ou wget est requis pour télécharger Synthea"
  exit 1
}

resolve_release_download_url() {
  if [[ -n "${SYNTHEA_JAR_URL:-}" ]]; then
    printf '%s\n' "${SYNTHEA_JAR_URL}"
    return
  fi
  if [[ -n "${RELEASE_TAG}" ]]; then
    printf '%s/download/%s/synthea-with-dependencies.jar\n' "${GITHUB_RELEASES_URL}" "${RELEASE_TAG}"
    return
  fi
  printf '%s/latest/download/synthea-with-dependencies.jar\n' "${GITHUB_RELEASES_URL}"
}

ensure_directories() {
  mkdir -p "${SYNTHEA_DIR}" "${BIN_DIR}" "${CONFIG_DIR}"
  mkdir -p "${SYNTHEA_DIR}/csv" "${SYNTHEA_DIR}/fhir"
}

ensure_synthea_jar() {
  if [[ -f "${JAR_PATH}" ]]; then
    log "JAR Synthea déjà présent: ${JAR_PATH}"
    return
  fi
  local url
  url="$(resolve_release_download_url)"
  log "Téléchargement Synthea depuis ${url}"
  download_with_curl_or_wget "${url}" "${JAR_PATH}.tmp"
  mv "${JAR_PATH}.tmp" "${JAR_PATH}"
}

write_synthea_config() {
  local config_path="${CONFIG_DIR}/synthea-fr.properties"
  cat >"${config_path}" <<EOF
exporter.baseDirectory = ${SYNTHEA_DIR}
exporter.csv.export = true
exporter.fhir.export = true
exporter.fhir.transaction_bundle = false
exporter.fhir.bulk_data = false
exporter.years_of_history = 2
exporter.csv.folder_per_run = false
exporter.fhir.folder_per_run = false
generate.database_type = none
generate.default_population = ${PATIENT_COUNT}
generate.only_dead_patients = false
generate.only_alive_patients = false
generate.track_detailed_transition_metrics = false
generate.log_patients.detail = none
EOF
  printf '%s\n' "${config_path}"
}

run_synthea() {
  local config_path="$1"
  local reference_date
  reference_date="$(date -u -v-"${MONTHS}"m +%Y%m%d 2>/dev/null || date -u +%Y%m%d)"
  log "Génération de ${PATIENT_COUNT} patients sur ${MONTHS} mois"
  java -jar "${JAR_PATH}" \
    -c "${config_path}" \
    -p "${PATIENT_COUNT}" \
    -s "${SEED}" \
    --exporter.fhir.export true \
    --exporter.csv.export true \
    --exporter.baseDirectory "${SYNTHEA_DIR}" \
    --generate.default_population "${PATIENT_COUNT}" \
    --generate.timestep 604800000 \
    --referenceTime "${reference_date}" \
    France
}

normalize_outputs() {
  local csv_count
  local fhir_count
  csv_count="$(find "${SYNTHEA_DIR}" -type f -name '*.csv' | wc -l | tr -d ' ')"
  fhir_count="$(find "${SYNTHEA_DIR}" -type f -name '*.json' | wc -l | tr -d ' ')"
  log "Fichiers CSV générés: ${csv_count}"
  log "Fichiers FHIR JSON générés: ${fhir_count}"
  if [[ "${csv_count}" -eq 0 ]]; then
    log "aucun CSV Synthea généré"
    exit 1
  fi
}

main() {
  require_command java
  ensure_directories
  ensure_synthea_jar
  local config_path
  config_path="$(write_synthea_config)"
  run_synthea "${config_path}"
  normalize_outputs
}

main "$@"
