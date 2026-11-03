#!/bin/sh
# Security headers of the web image on the page, a built asset and the API, through the real
# nginx (CI smoke test). nginx drops inherited add_header in a location that declares its own:
# without this check, the page itself could again be served without CSP nor X-Frame-Options.
#   WEB=http://127.0.0.1:8080 sh tools/check_web_headers.sh
set -eu
WEB=${WEB:-http://127.0.0.1:8080}
asset=$(curl -fsS "$WEB/" | grep -o '/assets/[^"]*\.js' | head -n 1)
[ -n "$asset" ] || { echo "::error title=headers::aucun fichier /assets/ dans la page"; exit 1; }
status=0
for path in / "$asset" /api/health; do
  headers=$(curl -sS -o /dev/null -D - "$WEB$path")
  for expected in \
    "x-frame-options: DENY" \
    "x-content-type-options: nosniff" \
    "referrer-policy: no-referrer" \
    "content-security-policy: default-src 'self'; img-src 'self' data: blob:"; do
    if ! printf '%s\n' "$headers" | grep -qiF "$expected"; then
      echo "::error title=headers::$path : en-tête manquant « $expected »"
      status=1
    fi
  done
done
[ "$status" -eq 0 ] && echo "En-têtes de sécurité présents sur /, $asset et /api/health."
exit "$status"
