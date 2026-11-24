#!/usr/bin/env bash
# Déploie une version d'HospitalOS sur le serveur de l'environnement, avec sauvegarde et retour arrière.
#
#   deploy.sh <staging|production> <image-tag>
#
# Exécuté sur le serveur (par la CI via SSH, ou à la main). Répertoire : /opt/hospitalos/<env>
# (HOSPITALOS_DIR pour un autre chemin), contenant docker-compose.yml, Caddyfile et .env.
# Si REGISTRY_USER est défini, le mot de passe du registre est lu sur l'entrée standard (jeton éphémère
# de la CI) ; la session docker est fermée après le téléchargement.
#
# Étapes : contrôle du tag -> sauvegarde de la base -> pull -> up -> attente de la santé publique
# (release = tag) -> en cas d'échec, retour automatique au tag précédent.
set -euo pipefail

ENV_NAME="${1:?usage: deploy.sh <staging|production> <image-tag>}"
TAG="${2:?usage: deploy.sh <staging|production> <image-tag>}"
case "$ENV_NAME" in staging | production) ;; *) echo "environnement inconnu : $ENV_NAME" >&2; exit 2 ;; esac
if ! [[ "$TAG" =~ ^(sha-[0-9a-f]{7,40}|v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?)$ ]]; then
  echo "tag d'image invalide : $TAG" >&2
  exit 2
fi
if [[ "$ENV_NAME" == production && "$TAG" != v* ]]; then
  echo "la production ne déploie que des versions étiquetées (vX.Y.Z)" >&2
  exit 2
fi

DIR="${HOSPITALOS_DIR:-/opt/hospitalos/$ENV_NAME}"
cd "$DIR"
[[ -f .env && -f docker-compose.yml && -f Caddyfile ]] || { echo "fichiers manquants dans $DIR" >&2; exit 2; }
chmod 600 .env

value() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2-; }
set_tag() { sed -i -E "s/^IMAGE_TAG=.*/IMAGE_TAG=$1/" .env; }
log() { printf '[deploy %s %s] %s\n' "$ENV_NAME" "$(date -u +%H:%M:%S)" "$*"; }

DOMAIN="$(value DOMAIN)"
REGISTRY="$(value REGISTRY)"
PREVIOUS="$(value IMAGE_TAG)"
[[ "$(value APP_ENV)" == "$ENV_NAME" ]] || { echo "APP_ENV du .env ne correspond pas à $ENV_NAME" >&2; exit 2; }

if [[ -n "${REGISTRY_USER:-}" ]]; then
  docker login "${REGISTRY%%/*}" -u "$REGISTRY_USER" --password-stdin >/dev/null
  trap 'docker logout "${REGISTRY%%/*}" >/dev/null 2>&1 || true' EXIT
fi

healthy() {
  local tag="$1" i
  for i in $(seq 1 40); do
    if curl -fsS --max-time 5 "https://$DOMAIN/api/platform/health" | grep -q "\"release\":\"$tag\""; then
      return 0
    fi
    sleep 3
  done
  return 1
}

# 1. Sauvegarde cohérente de la base des comptes avant tout changement (rétention 30 jours).
if docker compose ps --status running --services 2>/dev/null | grep -qx platform; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log "sauvegarde de la base (avant $TAG)"
  docker compose exec -T platform python -m hospitalos.platform backup "/data/backups/pre-$TAG-$stamp.sqlite3"
  docker compose exec -T platform find /data/backups -name '*.sqlite3' -mtime +30 -delete || true
fi

# 2. Nouvelle version.
log "déploiement $PREVIOUS -> $TAG"
set_tag "$TAG"
docker compose pull --quiet
docker compose up -d --remove-orphans

# 3. Vérification publique ; retour arrière sinon.
if healthy "$TAG"; then
  log "OK : https://$DOMAIN répond en $TAG"
  printf '%s\n' "$PREVIOUS" >.previous_tag
  docker image prune -f >/dev/null || true
  exit 0
fi

log "ÉCHEC de la vérification : retour à $PREVIOUS"
docker compose logs --tail 80 platform || true
if [[ -n "$PREVIOUS" && "$PREVIOUS" != "REPLACE_ME" ]]; then
  set_tag "$PREVIOUS"
  docker compose up -d --remove-orphans
  healthy "$PREVIOUS" && log "retour arrière effectué ($PREVIOUS)" || log "retour arrière NON vérifié : intervention requise"
fi
exit 1
