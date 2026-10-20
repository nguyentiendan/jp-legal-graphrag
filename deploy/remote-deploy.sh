#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run ON EC2 (called by GitHub Actions via SSH, or run manually).
#   IMAGE_PREFIX=ghcr.io/<owner>/jplegal IMAGE_TAG=<sha> ./deploy/remote-deploy.sh
# Registry token (optional) reads from stdin to avoid leaking in process list:
#   printf '%s' "$TOKEN" | REGISTRY_USER=<user> IMAGE_PREFIX=... IMAGE_TAG=... ./deploy/remote-deploy.sh
#
# Environment variables:
#   IMAGE_PREFIX, IMAGE_TAG   (required)
#   REGISTRY_USER             registry login user (pass token via stdin)
#   USE_GPU=false|true        add docker-compose.gpu.yml
#   ENABLE_OLLAMA=true|false  false = --scale ollama=0 --scale ollama-pull=0
#   HEALTH_TIMEOUT=900        seconds to wait for api/web healthy (first time model-server loads models ~1-2GB)
#   ROLLBACK=true             auto-rollback to previous tag if healthcheck fails
# ---------------------------------------------------------------------------
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

: "${IMAGE_PREFIX:?IMAGE_PREFIX is required}"
: "${IMAGE_TAG:?IMAGE_TAG is required}"
USE_GPU="${USE_GPU:-false}"
ENABLE_OLLAMA="${ENABLE_OLLAMA:-true}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-900}"
ROLLBACK="${ROLLBACK:-true}"
REGISTRY="${IMAGE_PREFIX%%/*}"

log() { printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }

# ---- check environment ----------------------------------------------------
command -v docker >/dev/null || { echo "docker not installed (run deploy/ec2-bootstrap.sh)"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "missing docker compose plugin"; exit 1; }
[ -f .env ] || { echo "Missing $APP_DIR/.env (create from .env.example or set secret ENV_FILE on GitHub)"; exit 1; }

COMPOSE_FILES=(-f docker-compose.yml)
[ "$USE_GPU" = "true" ] && COMPOSE_FILES+=(-f docker-compose.gpu.yml)
COMPOSE_FILES+=(-f docker-compose.prod.yml)   # luôn đặt cuối để !reset build có hiệu lực

SCALE_ARGS=()
[ "$ENABLE_OLLAMA" = "true" ] || SCALE_ARGS+=(--scale ollama=0 --scale ollama-pull=0)

dc() { docker compose --env-file .env --env-file .env.deploy "${COMPOSE_FILES[@]}" "$@"; }

# ---- registry login (token from stdin) ------------------------------------
TOKEN=""
if [ ! -t 0 ]; then TOKEN="$(cat || true)"; fi
LOGGED_IN=false
cleanup() { if [ "$LOGGED_IN" = "true" ]; then docker logout "$REGISTRY" >/dev/null 2>&1 || true; fi; }
trap cleanup EXIT
if [ -n "$TOKEN" ]; then
  log "docker login $REGISTRY"
  printf '%s' "$TOKEN" | docker login "$REGISTRY" -u "${REGISTRY_USER:-github-actions}" --password-stdin >/dev/null
  LOGGED_IN=true
fi

# ---- write new tag, keep previous tag for rollback --------------------------
PREV_TAG=""
if [ -f .env.deploy ]; then
  PREV_TAG="$(sed -n 's/^IMAGE_TAG=//p' .env.deploy | tail -1)"
  cp .env.deploy .env.deploy.prev
fi
umask 077
cat > .env.deploy <<EOF
IMAGE_PREFIX=${IMAGE_PREFIX}
IMAGE_TAG=${IMAGE_TAG}
EOF
mkdir -p data/import

wait_healthy() {
  local deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
  local svc cid status all_ok
  while :; do
    all_ok=true
    for svc in api web; do
      cid="$(dc ps -q "$svc" 2>/dev/null || true)"
      status="$( [ -n "$cid" ] && docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo missing)"
      [ "$status" = "healthy" ] || all_ok=false
      printf '  %-6s %s\n' "$svc" "$status"
    done
    $all_ok && return 0
    [ "$(date +%s)" -ge "$deadline" ] && return 1
    sleep 15
  done
}

deploy() {
  log "pull images (tag=$(sed -n 's/^IMAGE_TAG=//p' .env.deploy))"
  dc pull --quiet
  log "up -d"
  dc up -d --no-build --remove-orphans "${SCALE_ARGS[@]}"
}

log "Deploy $IMAGE_PREFIX:$IMAGE_TAG (prev=${PREV_TAG:-none}, gpu=$USE_GPU, ollama=$ENABLE_OLLAMA)"
deploy
log "Wait api & web healthy (timeout ${HEALTH_TIMEOUT}s)"
if wait_healthy; then
  log "Deploy OK: $IMAGE_TAG"
  dc ps
else
  log "Healthcheck FAIL — latest log:"
  dc logs --tail=80 api web model-server || true
  if [ "$ROLLBACK" = "true" ] && [ -f .env.deploy.prev ] && [ -n "$PREV_TAG" ] && [ "$PREV_TAG" != "$IMAGE_TAG" ]; then
    log "Rollback to $PREV_TAG"
    cp .env.deploy.prev .env.deploy
    deploy || true
    wait_healthy || log "Rollback also not healthy, check manually"
  fi
  exit 1
fi

# ---- clean up old app images (keep current tag and previous tag) ------------
log "Clean up old images"
docker image ls --format '{{.Repository}}:{{.Tag}}' \
  | grep -E "^${IMAGE_PREFIX//./\\.}/(api|worker|web|model-server):" \
  | grep -vE ":(${IMAGE_TAG}|${PREV_TAG:-__none__}|latest)$" \
  | xargs -r docker image rm >/dev/null 2>&1 || true
docker image prune -f >/dev/null 2>&1 || true
