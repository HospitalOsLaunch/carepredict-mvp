#!/bin/sh
# Compression of the web image through the real nginx (CI smoke test): a built JS file and a
# JSON answer of the API (proxied) must come gzipped when the browser accepts it.
#   WEB=http://127.0.0.1:8080 sh tools/check_web_compression.sh
set -eu
WEB=${WEB:-http://127.0.0.1:8080}
asset=$(curl -fsS "$WEB/" | grep -o '/assets/[^"]*\.js' | head -n 1)
[ -n "$asset" ] || { echo "::error title=compression::aucun fichier /assets/ dans la page"; exit 1; }
status=0
for path in "$asset" /api/vocabulary; do
  headers=$(curl -sS -o /dev/null -D - -H "Accept-Encoding: gzip" "$WEB$path")
  if printf '%s\n' "$headers" | grep -qi "^content-encoding: gzip"; then
    plain=$(curl -sS "$WEB$path" | wc -c)
    packed=$(curl -sS -H "Accept-Encoding: gzip" "$WEB$path" | wc -c)
    echo "$path : $plain → $packed octets (gzip)"
  else
    echo "::error title=compression::$path n'est pas compressé (Content-Encoding: gzip absent)"
    status=1
  fi
done
exit "$status"
