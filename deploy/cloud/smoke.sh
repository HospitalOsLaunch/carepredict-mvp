#!/usr/bin/env bash
# Vérifications publiques après un déploiement (CI ou à la main, depuis n'importe quel poste).
#
#   smoke.sh <url> <staging|production> <image-tag>
#   smoke.sh https://recette.example.fr staging sha-0123456789ab
set -euo pipefail

URL="${1:?usage: smoke.sh <url> <staging|production> <image-tag>}"
ENV_NAME="${2:?usage: smoke.sh <url> <staging|production> <image-tag>}"
TAG="${3:?usage: smoke.sh <url> <staging|production> <image-tag>}"
URL="${URL%/}"
fail=0
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }

health="$(curl -fsS --max-time 10 "$URL/api/platform/health" || true)"
config="$(curl -fsS --max-time 10 "$URL/api/config" || true)"
headers="$(curl -sS -o /dev/null -D - --max-time 10 "$URL/" | tr -d '\r' | tr '[:upper:]' '[:lower:]' || true)"
me_status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL/api/auth/me" || true)"
api_status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL/api/decision/state" || true)"

check "santé : version $TAG" '[[ "$health" == *"\"release\":\"$TAG\""* ]]'
check "santé : environnement $ENV_NAME" '[[ "$health" == *"\"environment\":\"$ENV_NAME\""* ]]'
check "configuration publique : environnement $ENV_NAME" '[[ "$config" == *"\"environment\":\"$ENV_NAME\""* ]]'
if [[ "$ENV_NAME" == production ]]; then
  check "mesure d'audience déclarée en production" '[[ "$config" == *"\"measurement_id\":\"G-"* ]]'
else
  check "aucune mesure d'audience hors production" '[[ "$config" == *"\"analytics\":null"* ]]'
  check "recette non indexée (X-Robots-Tag noindex)" '[[ "$headers" == *"x-robots-tag: noindex"* ]]'
fi
check "compte requis (/api/auth/me -> 401)" '[[ "$me_status" == 401 ]]'
check "moteurs fermés sans session (/api/decision -> 401)" '[[ "$api_status" == 401 ]]'
check "HSTS" '[[ "$headers" == *"strict-transport-security:"* ]]'
check "Content-Security-Policy" '[[ "$headers" == *"content-security-policy:"* ]]'
check "redirection HTTP -> HTTPS" \
  '[[ "$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://${URL#https://}/")" =~ ^30[178]$ ]]'
exit "$fail"
