#!/usr/bin/env bash
# Fast-forward the checked-out deployment branch, back up Docker data, rebuild,
# and verify the local health endpoint. Never resets or discards local changes.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BRANCH="${PRINTBUDDY_BRANCH:-main}"
SERVICE="${PRINTBUDDY_SERVICE:-printbuddy}"
HEALTH_URL="${PRINTBUDDY_HEALTH_URL:-http://127.0.0.1:${PORT:-8000}/health}"
HEALTH_TIMEOUT="${PRINTBUDDY_HEALTH_TIMEOUT:-180}"
BACKUP_ROOT="${PRINTBUDDY_BACKUP_DIR:-${REPO_ROOT}/backups}"
CONTAINER="${PRINTBUDDY_CONTAINER:-printbuddy}"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v git >/dev/null || die "git is required."
command -v docker >/dev/null || die "docker is required."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 plugin is required."
command -v curl >/dev/null || die "curl is required for the health check."
command -v flock >/dev/null || die "flock is required to prevent concurrent updates."

cd "$REPO_ROOT"
[[ -f docker-compose.yml ]] || die "docker-compose.yml was not found in ${REPO_ROOT}."
[[ -d .git ]] || die "This deployment is not a Git checkout. Clone the repository first."
exec 9>"${REPO_ROOT}/.update-server.lock"
flock -n 9 || die "Another Printbuddy update is already running."

CURRENT_BRANCH="$(git branch --show-current)"
[[ "$CURRENT_BRANCH" == "$BRANCH" ]] || die "Checked out branch is '${CURRENT_BRANCH:-detached}', expected '${BRANCH}'."
[[ -z "$(git status --porcelain)" ]] || die "Working tree is not clean. Commit or safely move local changes before updating."

git remote get-url origin >/dev/null 2>&1 || die "Git remote 'origin' is not configured."
git fetch --prune origin "$BRANCH"
OLD_COMMIT="$(git rev-parse HEAD)"
TARGET_COMMIT="$(git rev-parse "origin/${BRANCH}")"
[[ "$OLD_COMMIT" != "$TARGET_COMMIT" ]] || {
  printf 'Already up to date at %s.\n' "$OLD_COMMIT"
  exit 0
}

git merge-base --is-ancestor "$OLD_COMMIT" "$TARGET_COMMIT" || die "Remote branch is not a fast-forward from this checkout; no files were changed."

DATA_VOLUME="$(docker inspect "$CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Name}}{{end}}{{end}}' 2>/dev/null || true)"
[[ -n "$DATA_VOLUME" ]] || die "Could not identify /app/data volume on container '${CONTAINER}'. Start Printbuddy once before using this update script."

backup_failure() {
  local exit_code=$?
  trap - ERR
  docker compose up -d "$SERVICE" || printf 'WARNING: Printbuddy did not restart after backup failure.\n' >&2
  exit "$exit_code"
}

mkdir -p "$BACKUP_ROOT"
BACKUP_ROOT="$(cd -- "$BACKUP_ROOT" && pwd)"
chmod 700 "$BACKUP_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="${BACKUP_ROOT}/printbuddy-data-${STAMP}-${OLD_COMMIT:0:12}.tar.gz"
umask 077
docker compose stop "$SERVICE"
trap backup_failure ERR
printf 'Backing up Docker volume %s to %s\n' "$DATA_VOLUME" "$BACKUP_FILE"
docker run --rm \
  --mount "type=volume,source=${DATA_VOLUME},target=/data,readonly" \
  --mount "type=bind,source=${BACKUP_ROOT},target=/backup" \
  alpine:3.21 \
  sh -ec "tar czf '/backup/$(basename -- "$BACKUP_FILE")' -C /data ."
if [[ ! -s "$BACKUP_FILE" ]]; then
  docker compose up -d "$SERVICE" || true
  die "Data backup was not created; deployment remains unchanged."
fi
trap - ERR

printf 'Updating %s: %s -> %s\n' "$BRANCH" "${OLD_COMMIT:0:12}" "${TARGET_COMMIT:0:12}"

rollback() {
  local exit_code=$?
  trap - ERR
  printf 'Update failed (exit %s). Restoring source commit %s and rebuilding.\n' "$exit_code" "${OLD_COMMIT:0:12}" >&2
  git reset --keep "$OLD_COMMIT" || printf 'WARNING: could not restore the previous Git commit.\n' >&2
  docker compose up -d --build "$SERVICE" || printf 'WARNING: previous image could not be rebuilt.\n' >&2
  printf 'Data backup retained at: %s\n' "$BACKUP_FILE" >&2
  printf 'Database backup is not restored automatically because migrations may have changed its schema.\n' >&2
  exit "$exit_code"
}
trap rollback ERR

git merge --ff-only "origin/${BRANCH}"
docker compose config --quiet
docker compose up -d --build "$SERVICE"

printf 'Waiting for health endpoint: %s\n' "$HEALTH_URL"
deadline=$((SECONDS + HEALTH_TIMEOUT))
until curl --silent --fail "$HEALTH_URL" >/dev/null; do
  if (( SECONDS >= deadline )); then
    printf 'Health check timed out after %s seconds.\n' "$HEALTH_TIMEOUT" >&2
    false
  fi
  sleep 3
done

trap - ERR
printf 'Update complete at %s.\n' "$(git rev-parse --short HEAD)"
printf 'Pre-update data backup: %s\n' "$BACKUP_FILE"
docker compose ps "$SERVICE"
