#!/bin/sh
#
# Passive timing probe for Xiaomi native NLP results.
#
# Goal: compare when a new RESULT_NLP appears in the mibrain record file vs.
# when it becomes visible through ubus mibrain nlp_result_get.
#
# This script does not change wakeup hooks, freeze processes, or stop clients.

LOG_FILE="${LOG_FILE:-/tmp/native_result_timing_probe.log}"
RCD_FILE="${RCD_FILE:-/data/mibrain/mibrain_asr_nlp.rcd}"
POLL_SECONDS="${POLL_SECONDS:-18}"
POLL_INTERVAL="${POLL_INTERVAL:-0.2}"
RCD_POLL_INTERVAL="${RCD_POLL_INTERVAL:-1}"
UBUS_TIMEOUT="${UBUS_TIMEOUT:-1}"
LOCK_DIR="${LOCK_DIR:-/tmp/native_result_timing_probe.lock}"

log_ts() {
    if [ -r /proc/uptime ]; then
        awk '
            BEGIN {
                cmd = "date +%H:%M:%S"
                cmd | getline t
                close(cmd)
            }
            {
                ms = int(($1 - int($1)) * 1000)
                printf "%s.%03d", t, ms
            }
        ' /proc/uptime
    else
        date '+%H:%M:%S'
    fi
}

log() {
    echo "[$(log_ts)] $*" | tee -a "$LOG_FILE"
}

monotonic_ms() {
    awk '{ printf "%d", ($1 * 1000) }' /proc/uptime 2>/dev/null
}

elapsed_s() {
    local start_ms="$1"
    local now_ms

    now_ms=$(monotonic_ms)
    awk -v n="$now_ms" -v s="$start_ms" 'BEGIN { printf "%.2f", (n - s) / 1000 }'
}

extract_first_value() {
    local key="$1"
    grep -o "${key}[^,}]*: [^,}]*" \
        | head -1 \
        | sed 's/.*: *//; s/\\//g; s/"//g'
}

extract_request_id() {
    grep -o 'request_id[^,}]*: [^,}]*' \
        | head -1 \
        | sed 's/.*: *//; s/\\//g; s/"//g'
}

extract_meta_ts_ms() {
    grep -o 'timestamp[^,}]*: [0-9][0-9]*' \
        | tail -1 \
        | grep -o '[0-9][0-9]*' \
        | tail -1
}

extract_rcd_latest_nlp() {
    RCD_RAW=""
    RCD_REQ=""
    RCD_META_TS=""
    RCD_DOMAIN=""
    RCD_ACTION=""
    RCD_QUERY=""
    RCD_SPEAK=""

    [ -r "$RCD_FILE" ] || return 1
    RCD_RAW=$(
        strings "$RCD_FILE" 2>/dev/null \
            | grep 'RESULT_NLP' \
            | while IFS= read -r line; do
                ts=$(printf '%s\n' "$line" | extract_meta_ts_ms)
                [ -n "$ts" ] && printf '%s %s\n' "$ts" "$line"
            done \
            | sort -n \
            | tail -1 \
            | sed 's/^[0-9][0-9]* //'
    )
    [ -n "$RCD_RAW" ] || return 1

    RCD_REQ=$(printf '%s\n' "$RCD_RAW" | extract_request_id)
    RCD_META_TS=$(printf '%s\n' "$RCD_RAW" | extract_meta_ts_ms)
    RCD_DOMAIN=$(printf '%s\n' "$RCD_RAW" | extract_first_value domain)
    RCD_ACTION=$(printf '%s\n' "$RCD_RAW" | extract_first_value action)
    RCD_QUERY=$(printf '%s\n' "$RCD_RAW" | extract_first_value query)
    RCD_SPEAK=$(printf '%s\n' "$RCD_RAW" | extract_first_value to_speak)
    return 0
}

extract_ubus_latest_nlp() {
    local item raw="$1"

    UBUS_RAW=""
    UBUS_TS=""
    UBUS_REQ=""
    UBUS_META_TS=""
    UBUS_DOMAIN=""
    UBUS_ACTION=""
    UBUS_QUERY=""
    UBUS_SPEAK=""

    item=$(printf '%s\n' "$raw" | sed 's/}, {/\n/g' | grep '\\"nlp\\"' | head -1)
    [ -n "$item" ] || return 1

    UBUS_RAW="$item"
    UBUS_TS=$(printf '%s\n' "$item" | grep -o 'timestamp[^0-9]*[0-9][0-9]*' | head -1 | grep -o '[0-9][0-9]*' | head -1)
    UBUS_REQ=$(printf '%s\n' "$item" | extract_request_id)
    UBUS_META_TS=$(printf '%s\n' "$item" | extract_meta_ts_ms)
    UBUS_DOMAIN=$(printf '%s\n' "$item" | extract_first_value domain)
    UBUS_ACTION=$(printf '%s\n' "$item" | extract_first_value action)
    UBUS_QUERY=$(printf '%s\n' "$item" | extract_first_value query)
    UBUS_SPEAK=$(printf '%s\n' "$item" | extract_first_value to_speak)
    return 0
}

same_result() {
    local a="$1" b="$2"
    [ -n "$a" ] && [ -n "$b" ] && [ "$a" = "$b" ]
}

is_new_result() {
    local cur_req="$1" cur_meta="$2" base_req="$3" base_meta="$4"

    if [ -n "$cur_req" ] && [ -n "$base_req" ]; then
        [ "$cur_req" != "$base_req" ] && return 0
        return 1
    fi
    if [ -n "$cur_meta" ] && [ -n "$base_meta" ]; then
        [ "$cur_meta" != "$base_meta" ] && return 0
        return 1
    fi
    [ -n "$cur_req$cur_meta" ] && [ "$cur_req$cur_meta" != "$base_req$base_meta" ]
}

result_label() {
    local req="$1" meta_ts="$2" sec_ts="$3"
    if [ -n "$req" ]; then
        printf 'req=%s' "$req"
    elif [ -n "$meta_ts" ]; then
        printf 'meta_ts=%s' "$meta_ts"
    else
        printf 'ts=%s' "$sec_ts"
    fi
}

run_probe() {
    local base_rcd_req base_rcd_meta base_ubus_req base_ubus_meta
    local saw_rcd=0 saw_ubus=0
    local ticks total_ticks raw label rcd_every start_ms elapsed

    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        log "[LOCK] another probe is running: $LOCK_DIR"
        exit 1
    fi
    trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT INT TERM

    : > "$LOG_FILE"
    total_ticks=$(awk -v s="$POLL_SECONDS" -v p="$POLL_INTERVAL" 'BEGIN { printf "%d", (s / p) }')
    [ "$total_ticks" -gt 0 ] 2>/dev/null || total_ticks=90
    rcd_every=$(awk -v r="$RCD_POLL_INTERVAL" -v p="$POLL_INTERVAL" 'BEGIN { n = int(r / p); if (n < 1) n = 1; printf "%d", n }')
    start_ms=$(monotonic_ms)

    extract_rcd_latest_nlp
    base_rcd_req="$RCD_REQ"
    base_rcd_meta="$RCD_META_TS"

    raw=$(ubus -t "$UBUS_TIMEOUT" call mibrain nlp_result_get 2>&1)
    extract_ubus_latest_nlp "$raw"
    base_ubus_req="$UBUS_REQ"
    base_ubus_meta="$UBUS_META_TS"

    log "probe start ${POLL_SECONDS}s ubus_interval=${POLL_INTERVAL}s rcd_interval=${RCD_POLL_INTERVAL}s"
    log "baseline rcd $(result_label "$base_rcd_req" "$base_rcd_meta" "") domain=${RCD_DOMAIN:-?} query=${RCD_QUERY:-}"
    log "baseline ubus $(result_label "$base_ubus_req" "$base_ubus_meta" "$UBUS_TS") domain=${UBUS_DOMAIN:-?} query=${UBUS_QUERY:-}"
    log "现在说一句原生命令，例如：小爱同学，今天天气怎么样 / 小爱同学，开灯"

    ticks=0
    while [ "$ticks" -lt "$total_ticks" ]; do
        sleep "$POLL_INTERVAL"
        ticks=$((ticks + 1))

        if [ "$saw_rcd" -eq 0 ] && [ $((ticks % rcd_every)) -eq 0 ] && extract_rcd_latest_nlp; then
            if is_new_result "$RCD_REQ" "$RCD_META_TS" "$base_rcd_req" "$base_rcd_meta"; then
                label=$(result_label "$RCD_REQ" "$RCD_META_TS" "")
                elapsed=$(elapsed_s "$start_ms")
                log "[RCD] new elapsed=${elapsed}s ticks=${ticks} $label domain=${RCD_DOMAIN:-?} action=${RCD_ACTION:-?} query=${RCD_QUERY:-} speak=${RCD_SPEAK:-}"
                saw_rcd=1
            fi
        fi

        if [ "$saw_ubus" -eq 0 ]; then
            raw=$(ubus -t "$UBUS_TIMEOUT" call mibrain nlp_result_get 2>&1)
            if extract_ubus_latest_nlp "$raw"; then
                if is_new_result "$UBUS_REQ" "$UBUS_META_TS" "$base_ubus_req" "$base_ubus_meta"; then
                    label=$(result_label "$UBUS_REQ" "$UBUS_META_TS" "$UBUS_TS")
                    elapsed=$(elapsed_s "$start_ms")
                    log "[UBUS] new elapsed=${elapsed}s ticks=${ticks} $label ts=${UBUS_TS:-?} domain=${UBUS_DOMAIN:-?} action=${UBUS_ACTION:-?} query=${UBUS_QUERY:-} speak=${UBUS_SPEAK:-}"
                    saw_ubus=1
                fi
            fi
        fi

        [ "$saw_rcd" -eq 1 ] && [ "$saw_ubus" -eq 1 ] && break
    done

    if [ "$saw_rcd" -eq 0 ]; then
        log "[RCD] no new RESULT_NLP within ${POLL_SECONDS}s"
    fi
    if [ "$saw_ubus" -eq 0 ]; then
        log "[UBUS] no new RESULT_NLP within ${POLL_SECONDS}s"
    fi
    log "probe done: $LOG_FILE"
}

case "$1" in
    run|"")
        run_probe
        ;;
    log)
        tail -f "$LOG_FILE"
        ;;
    latest)
        extract_rcd_latest_nlp && log "[RCD] $(result_label "$RCD_REQ" "$RCD_META_TS" "") domain=${RCD_DOMAIN:-?} action=${RCD_ACTION:-?} query=${RCD_QUERY:-} speak=${RCD_SPEAK:-}"
        raw=$(ubus -t "$UBUS_TIMEOUT" call mibrain nlp_result_get 2>&1)
        extract_ubus_latest_nlp "$raw" && log "[UBUS] $(result_label "$UBUS_REQ" "$UBUS_META_TS" "$UBUS_TS") ts=${UBUS_TS:-?} domain=${UBUS_DOMAIN:-?} action=${UBUS_ACTION:-?} query=${UBUS_QUERY:-} speak=${UBUS_SPEAK:-}"
        ;;
    *)
        echo "Usage: $0 {run|log|latest}"
        echo "Env: POLL_SECONDS=18 POLL_INTERVAL=0.2 LOG_FILE=/tmp/native_result_timing_probe.log"
        exit 1
        ;;
esac
