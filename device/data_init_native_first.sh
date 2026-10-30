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
START_DELAY="${START_DELAY:-20}"
# 仅首问依赖自建服务时才等待；可选追问 ASR 不阻塞首问启动。
SERVER_WAIT_SECONDS="${SERVER_WAIT_SECONDS:-5}"
START_WITHOUT_SERVER="${START_WITHOUT_SERVER:-1}"

log() {
    echo "[$(date '+%H:%M:%S')] $*" >> "$LOG_FILE"
}

is_client_running() {
    ps | grep '[n]ative_first_client.sh' >/dev/null 2>&1
}

resolve_start_dependency() (
    # 与客户端一样读取可信 shell 配置。子 shell 隔离 LOG_FILE 等同名变量，
    # 且不把原始配置输出或源文件错误内容写入启动日志。
    if [ -f "$CONFIG_FILE" ]; then
        . "$CONFIG_FILE" >/dev/null 2>&1 || return 1
    fi
    case "${LLM_PIPELINE:-native}" in
        native)
            if [ "${TTS_ENGINE:-server}" = device ]; then
                printf 'none|'
            else
                printf 'tts|%s' "${TTS_SERVER:-${SERVER:-http://192.168.8.150:8080}}"
            fi
            ;;
        *) printf 'server|%s' "${SERVER:-http://192.168.8.150:8080}" ;;
    esac
)

wait_for_server() {
    local server="$1"
    local waited=0

    while [ "$waited" -lt "$SERVER_WAIT_SECONDS" ]; do
        if curl -s -o /dev/null -m 2 "$server/"; then
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
    done
    return 1
}

main() {
    local dependency kind server
    log "autostart begin client=$CLIENT"

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

    if ! dependency=$(resolve_start_dependency); then
        log "configuration load failed; client not started"
        exit 1
    fi
    kind=${dependency%%|*}
    server=${dependency#*|}
    log "startup dependency=$kind"
    if [ "$kind" = none ]; then
        log "native LLM + device TTS; skip server probe"
    elif wait_for_server "$server"; then
        log "server reachable"
    elif [ "$START_WITHOUT_SERVER" = "1" ]; then
        log "server not reachable after ${SERVER_WAIT_SECONDS}s, start client anyway"
    else
        log "server not reachable after ${SERVER_WAIT_SECONDS}s, skip client start"
        exit 0
    fi

    log "starting native-first client"
    CONFIG_FILE="$CONFIG_FILE" \
        sh "$CLIENT" >/tmp/native_first_client.log 2>&1 &
}

main "$@"
