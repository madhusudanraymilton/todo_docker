#!/usr/bin/env bash
set -euo pipefail

log() {
    echo "[entrypoint] $*"
}

file_env() {
    local var="$1"
    local file_var="${var}_FILE"
    local default="${2:-}"

    if [ "${!var:-}" ] && [ "${!file_var:-}" ]; then
        log "ERROR: both ${var} and ${file_var} are set"
        exit 1
    fi

    local value="$default"
    if [ "${!var:-}" ]; then
        value="${!var}"
    elif [ "${!file_var:-}" ]; then
        value="$(< "${!file_var}")"
    fi

    export "$var"="$value"
    unset "$file_var"
}

quote_sql_list() {
    awk '
        NF && !seen[$0]++ {
            gsub(/\047/, "\047\047")
            printf "%s\047%s\047", (n++ ? "," : ""), $0
        }
        END {
            if (n == 0) {
                printf "\047__no_modules__\047"
            }
        }
    '
}

custom_addon_names() {
    find /mnt/extra-addons -mindepth 2 -maxdepth 2 \
        \( -name "__manifest__.py" -o -name "__openerp__.py" \) \
        -printf '%h\n' 2>/dev/null | xargs -r -n1 basename
}

: "${HOST:=${DB_PORT_5432_TCP_ADDR:-db}}"
: "${PORT:=${DB_PORT_5432_TCP_PORT:-5432}}"
: "${USER:=${DB_ENV_POSTGRES_USER:-odoo}}"
: "${POSTGRES_DB:=postgres}"
: "${ODOO_DB_NAME:=odoo}"
: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${ODOO_BOOTSTRAP_MODULES:=base,web}"
: "${DB_WAIT_TIMEOUT:=60}"

file_env PASSWORD "${DB_ENV_POSTGRES_PASSWORD:-odoo}"
file_env ODOO_ADMIN_PASSWORD ""

export PGPASSWORD="$PASSWORD"

DB_ARGS=(
    --db_host "$HOST"
    --db_port "$PORT"
    --db_user "$USER"
    --db_password "$PASSWORD"
)

validate_db_name() {
    if [[ ! "$ODOO_DB_NAME" =~ ^[A-Za-z0-9_]+$ ]]; then
        log "ERROR: ODOO_DB_NAME must contain only letters, numbers, and underscores"
        exit 1
    fi
}

prepare_runtime_config() {
    local runtime_conf="/tmp/odoo.conf"

    cp "$ODOO_CONF" "$runtime_conf"
    if [ -n "${ODOO_ADMIN_PASSWORD:-}" ]; then
        {
            echo
            echo "admin_passwd = ${ODOO_ADMIN_PASSWORD}"
        } >> "$runtime_conf"
    fi

    ODOO_CONF="$runtime_conf"
}

wait_for_db() {
    log "Waiting for PostgreSQL at ${HOST}:${PORT} (user=${USER}, db=${POSTGRES_DB})..."
    local deadline=$((SECONDS + DB_WAIT_TIMEOUT))
    until pg_isready -h "$HOST" -p "$PORT" -U "$USER" -d "$POSTGRES_DB" -q; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            log "ERROR: PostgreSQL was not ready within ${DB_WAIT_TIMEOUT}s"
            exit 1
        fi
        sleep 2
    done
    log "PostgreSQL is ready."
}

db_exists() {
    psql -h "$HOST" -p "$PORT" -U "$USER" -d "$POSTGRES_DB" \
        -tAc "SELECT 1 FROM pg_database WHERE datname = '${ODOO_DB_NAME}'" \
        | grep -q 1
}

odoo_schema_exists() {
    db_exists || return 1

    psql -h "$HOST" -p "$PORT" -U "$USER" -d "$ODOO_DB_NAME" -tAc \
        "SELECT to_regclass('public.ir_module_module') IS NOT NULL;" \
        | grep -q t
}

bootstrap_db() {
    log "Bootstrapping Odoo database '${ODOO_DB_NAME}' with modules: ${ODOO_BOOTSTRAP_MODULES}"

    odoo \
        -c "$ODOO_CONF" \
        "${DB_ARGS[@]}" \
        -d "$ODOO_DB_NAME" \
        -i "$ODOO_BOOTSTRAP_MODULES" \
        --without-demo=all \
        --stop-after-init \
        --no-http

    log "Bootstrap complete."
}

render_lock_sql() {
    local installable_file="/opt/odoo-installable-modules.txt"
    local app_file="/opt/odoo-app-modules.txt"
    local template="/opt/lock_modules.sql"
    local out="/tmp/lock_modules.sql"

    for required in "$installable_file" "$app_file" "$template"; do
        if [ ! -f "$required" ]; then
            log "ERROR: missing required policy file: ${required}"
            exit 1
        fi
    done

    local installable
    installable=$(
        {
            cat "$installable_file"
            custom_addon_names
        } | quote_sql_list
    )

    local apps
    apps=$(
        {
            cat "$app_file"
            custom_addon_names
        } | quote_sql_list
    )

    sed \
        -e "s/__INSTALLABLE_PLACEHOLDER__/${installable}/g" \
        -e "s/__APP_PLACEHOLDER__/${apps}/g" \
        "$template" > "$out"

    echo "$out"
}

lock_modules() {
    if ! odoo_schema_exists; then
        log "Skipping module lock because Odoo schema is not initialized."
        return
    fi

    local sql
    sql="$(render_lock_sql)"

    log "Applying curated module lock."
    psql -h "$HOST" -p "$PORT" -U "$USER" -d "$ODOO_DB_NAME" -v ON_ERROR_STOP=1 -f "$sql"
    rm -f "$sql"
    log "Module lock applied."
}

case "${1:-odoo}" in
    -- | odoo)
        if [ "${1:-}" = "--" ]; then
            shift
        elif [ "${1:-}" = "odoo" ]; then
            shift
        fi

        if [ "${1:-}" = "scaffold" ]; then
            exec odoo "$@"
        fi

        validate_db_name
        prepare_runtime_config
        wait_for_db

        if ! db_exists; then
            bootstrap_db
        elif ! odoo_schema_exists; then
            log "Database exists but Odoo schema is missing. Bootstrapping now."
            bootstrap_db
        else
            log "Database and Odoo schema already exist. Skipping bootstrap."
        fi

        lock_modules

        log "Starting Odoo server."
        exec odoo -c "$ODOO_CONF" "${DB_ARGS[@]}" "$@"
        ;;
    -*)
        validate_db_name
        prepare_runtime_config
        wait_for_db
        exec odoo "$@" "${DB_ARGS[@]}"
        ;;
    *)
        exec "$@"
        ;;
esac
