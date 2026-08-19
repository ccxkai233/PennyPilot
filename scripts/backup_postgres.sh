#!/usr/bin/env bash

# Create an atomic PostgreSQL custom-format dump from the Compose database.
# The script deliberately talks to PostgreSQL through the db container, so the
# host does not need pg_dump installed.

set -Eeuo pipefail

PP_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PP_PROJECT_DIR="$(cd -- "$PP_SCRIPT_DIR/.." && pwd -P)"
PP_DB_SERVICE="${PENNYPILOT_DB_SERVICE:-db}"
PP_BACKUP_DIR="${PENNYPILOT_BACKUP_DIR:-$PP_PROJECT_DIR/backups}"
PP_FORCE="${PENNYPILOT_BACKUP_FORCE:-0}"
PP_ENV_FILE="${PENNYPILOT_COMPOSE_ENV_FILE:-}"

usage() {
    cat <<'USAGE'
Usage: scripts/backup_postgres.sh [OUTPUT_FILE] [--force]

Create a PostgreSQL custom-format backup. A relative output path is resolved
against the PennyPilot project root. If no path is supplied, a UTC timestamped
file is created under backups/.

Environment:
  PENNYPILOT_DB_SERVICE   Compose service name (default: db)
  PENNYPILOT_COMPOSE_ENV_FILE
                          Optional Compose env file (auto-detects .env, then
                          /etc/pennypilot/compose.env)
  PENNYPILOT_BACKUP_DIR   Default output directory
  PENNYPILOT_BACKUP_FORCE Set to 1 to allow replacing an existing file
USAGE
}

die() {
    echo "backup_postgres: $*" >&2
    exit 1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

PP_OUTPUT=""
while (($#)); do
    case "$1" in
        --force)
            PP_FORCE=1
            ;;
        --)
            shift
            if (($# != 1)); then
                usage >&2
                exit 2
            fi
            PP_OUTPUT="$1"
            break
            ;;
        -* )
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            if [[ -n "$PP_OUTPUT" ]]; then
                echo "Only one output file may be supplied" >&2
                usage >&2
                exit 2
            fi
            PP_OUTPUT="$1"
            ;;
    esac
    shift
done

if [[ -z "$PP_OUTPUT" ]]; then
    PP_OUTPUT="$PP_BACKUP_DIR/pennypilot_$(date -u +%Y%m%dT%H%M%SZ).dump"
fi
if [[ "$PP_OUTPUT" != /* ]]; then
    PP_OUTPUT="$PP_PROJECT_DIR/$PP_OUTPUT"
fi

[[ "$PP_OUTPUT" != "/" ]] || die "refusing to use / as the output file"
if [[ -e "$PP_OUTPUT" && "$PP_FORCE" != "1" ]]; then
    die "output already exists: $PP_OUTPUT (pass --force to replace it)"
fi

mkdir -p -- "$(dirname -- "$PP_OUTPUT")"
umask 077

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

# Read the effective database settings from the running container. This keeps
# custom values in .env working without evaluating that file as shell code.
PP_DB_ENV="$("${PP_COMPOSE[@]}" exec -T "$PP_DB_SERVICE" sh -c \
    'printf "%s\n%s\n%s\n" "${POSTGRES_DB:-pennypilot}" "${POSTGRES_USER:-pennypilot}" "${POSTGRES_PASSWORD:-pennypilot_dev_password}"')" ||
    die "could not read PostgreSQL container settings"
PP_DB_NAME="$(sed -n '1p' <<<"$PP_DB_ENV" | tr -d '\r')"
PP_DB_USER="$(sed -n '2p' <<<"$PP_DB_ENV" | tr -d '\r')"
PP_DB_PASSWORD="$(sed -n '3p' <<<"$PP_DB_ENV" | tr -d '\r')"
[[ -n "$PP_DB_NAME" && -n "$PP_DB_USER" ]] || die "container returned empty database settings"

PP_TMP="$(mktemp "${PP_OUTPUT}.tmp.XXXXXX")"
cleanup() {
    rm -f -- "$PP_TMP"
}
trap cleanup EXIT

echo "Creating PostgreSQL backup: $PP_OUTPUT"
if ! "${PP_COMPOSE[@]}" exec -T -e "PGPASSWORD=$PP_DB_PASSWORD" "$PP_DB_SERVICE" \
    pg_dump --format=custom --no-owner --no-privileges --dbname="$PP_DB_NAME" --username="$PP_DB_USER" \
    >"$PP_TMP"; then
    die "pg_dump failed"
fi
[[ -s "$PP_TMP" ]] || die "pg_dump produced an empty file"

# Validate the archive before making it visible at its final path.
if ! "${PP_COMPOSE[@]}" exec -T "$PP_DB_SERVICE" pg_restore --list <"$PP_TMP" >/dev/null; then
    die "pg_restore could not read the generated archive"
fi

mv -f -- "$PP_TMP" "$PP_OUTPUT"
trap - EXIT

if command -v sha256sum >/dev/null 2>&1; then
    (cd -- "$(dirname -- "$PP_OUTPUT")" && sha256sum -- "$(basename -- "$PP_OUTPUT")") >"$PP_OUTPUT.sha256"
    chmod 600 -- "$PP_OUTPUT.sha256"
fi
chmod 600 -- "$PP_OUTPUT"

echo "Backup complete: $PP_OUTPUT ($(du -h -- "$PP_OUTPUT" | awk '{print $1}'))"
