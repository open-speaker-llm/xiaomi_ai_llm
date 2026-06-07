#!/bin/sh
#
# /data/init.sh template for native-first autostart.
#
# This file is meant to be copied to the speaker as /data/init.sh after the
# rootfs has a one-line rc.local hook:
#   [ -f "/data/init.sh" ] && sh /data/init.sh >/dev/null 2>&1 &

LOG_FILE="${LOG_FILE:-/tmp/native_first_autostart.log}"
CLIENT="${CLIENT:-/data/native_first_client.sh}"
CONFIG_FILE="${CONFIG_FILE:-/data/native_first.env}"
SERVER="${SERVER:-http://192.168.8.150:8080}"
BACKEND="${BACKEND:-deepseek}"
START_DELAY="${START_DELAY:-20}"
SERVER_WAIT_SECONDS="${SERVER_WAIT_SECONDS:-90}"
START_WITHOUT_SERVER="${START_WITHOUT_SERVER:-1}"

log() {
    echo "[$(date '+%H:%M:%S')] $*" >> "$LOG_FILE"
}

is_client_running() {
    ps | grep '[n]ative_first_client.sh' >/dev/null 2>&1
}

wait_for_server() {
    local waited=0

    while [ "$waited" -lt "$SERVER_WAIT_SECONDS" ]; do
        if curl -s -o /dev/null -m 2 "$SERVER/"; then
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
    done
    return 1
}

main() {
    log "autostart begin client=$CLIENT server=$SERVER backend=$BACKEND"

    sleep "$START_DELAY"

    if [ ! -x "$CLIENT" ]; then
        chmod +x "$CLIENT" 2>/dev/null
    fi
    if [ ! -f "$CLIENT" ]; then
        log "client not found: $CLIENT"
        exit 0
    fi

    if is_client_running; then
        log "client already running"
        exit 0
    fi

    if wait_for_server; then
        log "server reachable"
    elif [ "$START_WITHOUT_SERVER" = "1" ]; then
        log "server not reachable after ${SERVER_WAIT_SECONDS}s, start client anyway"
    else
        log "server not reachable after ${SERVER_WAIT_SECONDS}s, skip client start"
        exit 0
    fi

    log "starting native-first client"
    SERVER="$SERVER" BACKEND="$BACKEND" CONFIG_FILE="$CONFIG_FILE" \
        sh "$CLIENT" >/tmp/native_first_client.log 2>&1 &
}

main "$@"
