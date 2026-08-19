#!/usr/bin/env bash

# Restore a custom-format PostgreSQL dump into the existing Compose database.
# This is intentionally guarded: an explicit --confirm is required because
# pg_restore --clean removes objects contained in the dump before recreating
# them.

set -Eeuo pipefail

PP_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PP_PROJECT_DIR="$(cd -- "$PP_SCRIPT_DIR/.." && pwd -P)"
PP_DB_SERVICE="${PENNYPILOT_DB_SERVICE:-db}"
PP_CONFIRM=0
PP_SKIP_SAFETY="${PENNYPILOT_RESTORE_SKIP_SAFETY_BACKUP:-0}"
PP_ENV_FILE="${PENNYPILOT_COMPOSE_ENV_FILE:-}"

usage() {
    cat <<'USAGE'
Usage: scripts/restore_postgres.sh BACKUP_FILE --confirm

Restore a custom-format PostgreSQL backup into the Compose database. The
explicit --confirm flag is mandatory. Before restoring, a safety backup of
the current database is created in the same directory unless
PENNYPILOT_RESTORE_SKIP_SAFETY_BACKUP=1 is set.

Environment:
  PENNYPILOT_DB_SERVICE                 Compose service name (default: db)
  PENNYPILOT_COMPOSE_ENV_FILE           Optional Compose env file (auto-detects
                                        .env, then /etc/pennypilot/compose.env)
  PENNYPILOT_RESTORE_SKIP_SAFETY_BACKUP Set to 1 only when a safety dump is
                                        already available
USAGE
}

die() {
    echo "restore_postgres: $*" >&2
    exit 1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 ]]; then
    usage >&2
    [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && exit 0
    exit 2
fi

PP_BACKUP="$1"
shift
if [[ "$PP_BACKUP" != /* ]]; then
    PP_BACKUP="$PWD/$PP_BACKUP"
fi
PP_BACKUP="$(cd -- "$(dirname -- "$PP_BACKUP")" && pwd -P)/$(basename -- "$PP_BACKUP")"

while (($#)); do
    case "$1" in
        --confirm) PP_CONFIRM=1 ;;
        --skip-safety-backup) PP_SKIP_SAFETY=1 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

[[ "$PP_CONFIRM" == "1" ]] || die "restore is destructive; pass --confirm explicitly"
[[ -f "$PP_BACKUP" ]] || die "backup file not found: $PP_BACKUP"
[[ -s "$PP_BACKUP" ]] || die "backup file is empty: $PP_BACKUP"

PP_COMPOSE=(docker compose --project-directory "$PP_PROJECT_DIR")
if [[ -z "$PP_ENV_FILE" ]]; then
    if [[ -f "$PP_PROJECT_DIR/.env" ]]; then
        PP_ENV_FILE="$PP_PROJECT_DIR/.env"
    elif [[ -f "/etc/pennypilot/compose.env" ]]; then
        PP_ENV_FILE="/etc/pennypilot/compose.env"
    fi
fi
if [[ -n "$PP_ENV_FILE" ]]; then
    [[ -f "$PP_ENV_FILE" ]] || die "Compose env file not found: $PP_ENV_FILE"
    PP_COMPOSE+=(--env-file "$PP_ENV_FILE")
fi

if ! "${PP_COMPOSE[@]}" ps --status running --services 2>/dev/null |
    awk -v service="$PP_DB_SERVICE" '$0 == service { found = 1 } END { exit(found ? 0 : 1) }'; then
    die "Compose service '$PP_DB_SERVICE' is not running; start it with 'docker compose up -d db'"
fi

PP_DB_ENV="$("${PP_COMPOSE[@]}" exec -T "$PP_DB_SERVICE" sh -c \
    'printf "%s\n%s\n%s\n" "${POSTGRES_DB:-pennypilot}" "${POSTGRES_USER:-pennypilot}" "${POSTGRES_PASSWORD:-pennypilot_dev_password}"')" ||
    die "could not read PostgreSQL container settings"
PP_DB_NAME="$(sed -n '1p' <<<"$PP_DB_ENV" | tr -d '\r')"
PP_DB_USER="$(sed -n '2p' <<<"$PP_DB_ENV" | tr -d '\r')"
PP_DB_PASSWORD="$(sed -n '3p' <<<"$PP_DB_ENV" | tr -d '\r')"
[[ -n "$PP_DB_NAME" && -n "$PP_DB_USER" ]] || die "container returned empty database settings"

echo "Validating backup archive..."
if ! "${PP_COMPOSE[@]}" exec -T "$PP_DB_SERVICE" pg_restore --list <"$PP_BACKUP" >/dev/null; then
    die "the backup is not a readable PostgreSQL custom-format archive"
fi

if [[ "$PP_SKIP_SAFETY" != "1" ]]; then
    PP_SAFETY="$PP_BACKUP.safety-$(date -u +%Y%m%dT%H%M%SZ).dump"
    echo "Creating safety backup: $PP_SAFETY"
    if ! "$PP_SCRIPT_DIR/backup_postgres.sh" "$PP_SAFETY"; then
        die "safety backup failed; restore was not attempted"
    fi
fi

echo "Restoring '$PP_BACKUP' into database '$PP_DB_NAME'..."
if ! "${PP_COMPOSE[@]}" exec -T -e "PGPASSWORD=$PP_DB_PASSWORD" "$PP_DB_SERVICE" \
    pg_restore --clean --if-exists --exit-on-error --single-transaction \
    --no-owner --no-privileges --dbname="$PP_DB_NAME" --username="$PP_DB_USER" \
    <"$PP_BACKUP"; then
    die "pg_restore failed; inspect the database and safety backup"
fi

echo "Restore complete. Run the migration check and application health check before serving traffic."
