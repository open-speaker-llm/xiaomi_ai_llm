#!/bin/sh
#
# Probe native Xiaomi ASR reopen triggers without relying on local recording.
# It snapshots mico_aivs_lab logs, fires one candidate trigger, then reports
# whether AIVS wrote ExpectSpeech/RecognizeResult/Speak/Finish events.
#

LOG_FILE="${LOG_FILE:-/tmp/native_reopen_probe.log}"
INSTRUCTION_LOG="${INSTRUCTION_LOG:-/tmp/mico_aivs_lab/instruction.log}"
EVENT_LOG="${EVENT_LOG:-/tmp/mico_aivs_lab/event.log}"
WAIT_SECONDS="${WAIT_SECONDS:-4}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"

now_ts() {
    local ms
    ms=$(cut -d' ' -f1 /proc/uptime 2>/dev/null | awk -F. '{printf "%03d", $2}' 2>/dev/null)
    [ -n "$ms" ] || ms="000"
    echo "$(date '+%H:%M:%S').$ms"
}

log() { echo "[$(now_ts)] $*" | tee -a "$LOG_FILE"; }

json_escape() {
    sed 's/\\/\\\\/g; s/"/\\"/g'
}

line_count() {
    [ -f "$1" ] || {
        echo 0
        return
    }
    wc -l < "$1" 2>/dev/null | tr -d ' '
}

dump_delta() {
    local label="$1"
    local file="$2"
    local start_line="$3"
    local total from

    total=$(line_count "$file")
    from=$((start_line + 1))
    log "--- ${label} delta lines ${from}-${total} file=$file ---"
    if [ "$total" -ge "$from" ] 2>/dev/null; then
        sed -n "${from},${total}p" "$file" 2>/dev/null | tee -a "$LOG_FILE"
    else
        log "(no new lines)"
    fi
}

snapshot_state() {
    log "processes: $(ps | grep -E 'mico_aivs_lab|mipns-xiaomi|mibrain_service|native_first_client' | grep -v grep | sed 's/^/  /' | tr '\n' ';')"
    log "dialog_continuous=$(cat /data/mipns/dialog_continuous 2>/dev/null)"
    log "oneshot=$(ubus -t 1 call pnshelper oneshot_get 2>/dev/null | tr '\n' ' ')"
}

trigger_pns() {
    local event="$1"
    local detail="$2"
    log "[TRIGGER] pnshelper event_notify src=3 event=$event detail=$detail"
    ubus -t 2 call pnshelper event_notify "{\"src\":3,\"event\":$event,\"detail\":\"$detail\"}" 2>&1 | tee -a "$LOG_FILE"
}

trigger_wakeup_multirounds() {
    log "[TRIGGER] wakeup.sh multirounds"
    if [ -x "$ORIG_WAKEUP" ]; then
        "$ORIG_WAKEUP" multirounds 2>&1 | tee -a "$LOG_FILE"
    elif [ -x /bin/wakeup.sh ]; then
        /bin/wakeup.sh multirounds 2>&1 | tee -a "$LOG_FILE"
    else
        log "wakeup.sh not found"
        return 1
    fi
}

trigger_oneshot() {
    local open="$1"

    [ -n "$open" ] || open="true"
    log "[TRIGGER] pnshelper oneshot_set open=$open"
    ubus -t 2 call pnshelper oneshot_set "{\"open\":$open}" 2>&1 | tee -a "$LOG_FILE"
}

trigger_aivs_event() {
    local namespace="$1"
    local name="$2"
    local payload="$3"
    local safe_payload

    [ -n "$payload" ] || payload="{}"
    safe_payload=$(printf '%s' "$payload" | json_escape)
    log "[TRIGGER] mibrain aivs_event_post namespace=$namespace name=$name payload=$payload"
    ubus -t 3 call mibrain aivs_event_post "{\"namespace\":\"$namespace\",\"name\":\"$name\",\"payload\":\"$safe_payload\"}" 2>&1 | tee -a "$LOG_FILE"
}

run_one() {
    local mode="$1"
    local a="$2"
    local b="$3"
    local c="$4"
    local ins0 event0

    : > "$LOG_FILE"
    snapshot_state
    ins0=$(line_count "$INSTRUCTION_LOG")
    event0=$(line_count "$EVENT_LOG")
    log "baseline instruction_lines=$ins0 event_lines=$event0"

    case "$mode" in
        pns)
            trigger_pns "$a" "$b"
            ;;
        wakeup_multirounds)
            trigger_wakeup_multirounds
            ;;
        oneshot)
            trigger_oneshot "$a"
            ;;
        aivs)
            trigger_aivs_event "$a" "$b" "$c"
            ;;
        *)
            log "unknown mode: $mode"
            return 2
            ;;
    esac

    log "wait ${WAIT_SECONDS}s; if testing ASR, speak now without wake word"
    sleep "$WAIT_SECONDS"
    dump_delta instruction "$INSTRUCTION_LOG" "$ins0"
    dump_delta event "$EVENT_LOG" "$event0"
    log "summary grep:"
    grep -E 'ExpectSpeech|RecognizeResult|Recognize|StopCapture|Speak|Finish|Continuous|DialogState|Wakeup' "$LOG_FILE" 2>/dev/null | tail -80
}

run_matrix() {
    : > "$LOG_FILE"
    log "matrix start wait=$WAIT_SECONDS"
    sh "$0" pns 4 pre_multirounds
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" pns 4 stop_session
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" pns 4 pns_start
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" pns 4 pns_stop
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" pns 4 tts_start
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" pns 4 tts_end
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" aivs Dialog TurnOnContinuousDialog '{}'
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" aivs Dialog EnterTemporaryContinuousDialog '{}'
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" aivs SpeechRecognizer ExpectSpeech '{}'
    echo "" >> "$LOG_FILE"; sleep 1
    sh "$0" wakeup_multirounds
    echo "" >> "$LOG_FILE"; sleep 1
    log "matrix done"
}

case "$1" in
    pns)
        run_one pns "${2:-4}" "${3:-pre_multirounds}"
        ;;
    oneshot)
        open_arg="$2"
        [ -n "$open_arg" ] || open_arg="true"
        run_one oneshot "$open_arg"
        ubus -t 2 call pnshelper oneshot_set '{"open":false}' >/dev/null 2>&1
        ;;
    wakeup_multirounds)
        run_one wakeup_multirounds
        ;;
    aivs)
        payload_arg="$4"
        [ -n "$payload_arg" ] || payload_arg="{}"
        run_one aivs "$2" "$3" "$payload_arg"
        ;;
    matrix)
        run_matrix
        ;;
    log)
        tail -f "$LOG_FILE" "$INSTRUCTION_LOG" "$EVENT_LOG"
        ;;
    *)
        echo "Usage:"
        echo "  $0 pns <event> <detail>"
        echo "  $0 oneshot [true|false]"
        echo "  $0 wakeup_multirounds"
        echo "  $0 aivs <namespace> <name> [payload_json]"
        echo "  $0 matrix"
        echo "  $0 log"
        exit 1
        ;;
esac
