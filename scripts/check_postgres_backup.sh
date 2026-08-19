#!/usr/bin/env bash

# Read-only validation for a PostgreSQL custom-format dump. No database
# objects are changed; the db container is used only when pg_restore is not
# installed on the host.

set -Eeuo pipefail

PP_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PP_PROJECT_DIR="$(cd -- "$PP_SCRIPT_DIR/.." && pwd -P)"
PP_DB_SERVICE="${PENNYPILOT_DB_SERVICE:-db}"
PP_ENV_FILE="${PENNYPILOT_COMPOSE_ENV_FILE:-}"

usage() {
    cat <<'USAGE'
Usage: scripts/check_postgres_backup.sh BACKUP_FILE

Validate that BACKUP_FILE is a readable PostgreSQL custom-format archive and,
when present, verify its .sha256 sidecar file. This command does not alter the
database.
USAGE
}

die() {
    echo "check_postgres_backup: $*" >&2
    exit 1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -ne 1 ]]; then
    usage >&2
    [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && exit 0
    exit 2
fi

PP_BACKUP="$1"
if [[ "$PP_BACKUP" != /* ]]; then
    PP_BACKUP="$PWD/$PP_BACKUP"
fi
PP_BACKUP="$(cd -- "$(dirname -- "$PP_BACKUP")" && pwd -P)/$(basename -- "$PP_BACKUP")"
[[ -f "$PP_BACKUP" ]] || die "backup file not found: $PP_BACKUP"
[[ -s "$PP_BACKUP" ]] || die "backup file is empty: $PP_BACKUP"

if [[ -f "$PP_BACKUP.sha256" ]]; then
    (cd -- "$(dirname -- "$PP_BACKUP")" && sha256sum --check --status "$(basename -- "$PP_BACKUP.sha256")") ||
        die "SHA-256 sidecar verification failed"
    echo "SHA-256: ok"
fi

if command -v pg_restore >/dev/null 2>&1; then
    PP_TOC="$(pg_restore --list -- "$PP_BACKUP")" || die "pg_restore rejected the archive"
else
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
        die "pg_restore is not installed on the host and Compose service '$PP_DB_SERVICE' is not running"
    fi
    PP_TOC="$("${PP_COMPOSE[@]}" exec -T "$PP_DB_SERVICE" pg_restore --list <"$PP_BACKUP")" ||
        die "container pg_restore rejected the archive"
fi

PP_ENTRIES="$(awk 'NF && $1 !~ /^#/ { count++ } END { print count + 0 }' <<<"$PP_TOC")"
[[ "$PP_ENTRIES" -gt 0 ]] || die "archive contains no dump entries"
echo "Backup is valid: $PP_BACKUP ($PP_ENTRIES dump entries)"
