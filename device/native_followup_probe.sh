#!/bin/sh
#
# Probe whether Xiaomi's native ASR/NLP can be triggered without saying the
# wake word. This is for validating native-ASR follow-up turns.
#

LOG_FILE="${LOG_FILE:-/tmp/native_followup_probe.log}"
RAW_FILE="${RAW_FILE:-/tmp/native_followup_probe_raw.log}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"
MIPNS_CONF="${MIPNS_CONF:-/usr/share/xiaomi/xaudio_engine.conf}"
POLL_SECONDS="${POLL_SECONDS:-12}"
POLL_INTERVAL="${POLL_INTERVAL:-1}"
AI_DURATION="${AI_DURATION:-5}"
NLP_EXECUTE="${NLP_EXECUTE:-0}"
TTS_ENABLE="${TTS_ENABLE:-0}"
VAD_SCRIPT="${VAD_SCRIPT:-/data/vad_record.sh}"
VOICE_FILE="${VOICE_FILE:-/tmp/voice.wav}"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG_FILE"; }

json_escape() {
    sed 's/\\/\\\\/g; s/"/\\"/g'
}

restore_hook() {
    while mount | grep -q ' on /bin/wakeup.sh '; do
        umount /bin/wakeup.sh 2>/dev/null
        sleep 0.1
    done
}

start_mipns() {
    if pidof mipns-xiaomi >/dev/null 2>&1; then
        killall -CONT mipns-xiaomi 2>/dev/null
    else
        /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" >/tmp/native_mipns.log 2>&1 &
    fi
}

stop_project_clients() {
    killall curl 2>/dev/null
    killall aplay 2>/dev/null
    killall arecord 2>/dev/null
    ps | grep -E 'native_first_client.sh|native_client.sh|stream_client.sh|wake_monitor.sh|vad_record.sh|native_first_observer.sh' \
        | grep -v grep | awk '{print $1}' | xargs -r kill -9 2>/dev/null
    ps | grep -E 'native_first_cl|native_client|stream_client|wake_monitor|vad_record' \
        | grep -v grep | awk '{print $1}' | xargs -r kill -9 2>/dev/null
    rm -f /tmp/native_first_busy /tmp/native_first_player_frozen /tmp/stream_fifo
}

extract_first_value() {
    local key="$1"
    grep -o "${key}[^,}]*: [^,}]*" | head -1 | awk -F'\\\\\\"' '{print $3}' | sed 's/\\*$//'
}

extract_latest_result() {
    local raw="$1"
    local item

    RESULT_TS=""
    RESULT_DOMAIN=""
    RESULT_ACTION=""
    RESULT_QUERY=""
    RESULT_SPEAK=""

    item=$(echo "$raw" | sed 's/}, {/\n/g' | grep '\\"nlp\\"' | head -1)
    [ -n "$item" ] || return 1

    RESULT_TS=$(echo "$item" | grep -o 'timestamp[^0-9]*[0-9][0-9]*' | head -1 | grep -o '[0-9][0-9]*' | head -1)
    RESULT_DOMAIN=$(echo "$item" | extract_first_value domain)
    RESULT_ACTION=$(echo "$item" | extract_first_value action)
    RESULT_QUERY=$(echo "$item" | extract_first_value query)
    RESULT_SPEAK=$(echo "$item" | extract_first_value to_speak)
    return 0
}

call_ai_service_asr() {
    local id="native_followup_probe_$(date +%s)"
    local payload

    payload="{\"bypass\":\"\",\"caller\":\"native_followup_probe\",\"duration\":$AI_DURATION,\"id\":\"$id\",\"asr\":1,\"nlp\":1,\"tts\":$TTS_ENABLE,\"asr_audio\":\"\",\"nlp_text\":\"\",\"nlp_execute\":$NLP_EXECUTE,\"tts_text\":\"\",\"tts_type\":\"\",\"tts_vendor\":\"\",\"tts_volume\":80,\"tts_codec\":\"mp3\",\"tts_save\":0,\"tts_play\":$TTS_ENABLE}"
    log "[CALL] ai_service id=$id duration=$AI_DURATION asr=1 nlp=1 tts=$TTS_ENABLE nlp_execute=$NLP_EXECUTE"
    ubus -t "$((AI_DURATION + 10))" call mibrain ai_service "$payload"
    log "[CALL] ai_service returned ret=$?"
}

call_ai_service_audio_file() {
    local audio_file="$1"
    local id="native_audio_probe_$(date +%s)"
    local payload
    local safe_audio

    safe_audio=$(printf '%s' "$audio_file" | json_escape)
    payload="{\"bypass\":\"\",\"caller\":\"native_followup_probe\",\"duration\":0,\"id\":\"$id\",\"asr\":1,\"nlp\":1,\"tts\":$TTS_ENABLE,\"asr_audio\":\"$safe_audio\",\"nlp_text\":\"\",\"nlp_execute\":$NLP_EXECUTE,\"tts_text\":\"\",\"tts_type\":\"\",\"tts_vendor\":\"\",\"tts_volume\":80,\"tts_codec\":\"mp3\",\"tts_save\":0,\"tts_play\":$TTS_ENABLE}"
    log "[CALL] ai_service file id=$id asr_audio=$audio_file asr=1 nlp=1 tts=$TTS_ENABLE nlp_execute=$NLP_EXECUTE"
    ubus -t 30 call mibrain ai_service "$payload"
    log "[CALL] ai_service file returned ret=$?"
}

poll_native_result() {
    local start_ts="$1"
    local i=0
    local raw

    : > "$RAW_FILE"
    while [ "$i" -lt "$POLL_SECONDS" ]; do
        sleep "$POLL_INTERVAL"
        raw=$(ubus -t 2 call mibrain nlp_result_get 2>&1)
        {
            echo "----- poll $((i + 1)) $(date '+%H:%M:%S') -----"
            echo "$raw"
        } >> "$RAW_FILE"

        if extract_latest_result "$raw"; then
            log "[POLL] ts=${RESULT_TS:-?} domain=${RESULT_DOMAIN:-?} action=${RESULT_ACTION:-?} query=${RESULT_QUERY:-} speak=${RESULT_SPEAK:-}"
            if [ -n "$RESULT_TS" ] && [ "$RESULT_TS" -ge "$start_ts" ] 2>/dev/null && [ -n "$RESULT_QUERY" ]; then
                log "[OK] got native query after probe: $RESULT_QUERY"
                return 0
            fi
        else
            log "[POLL] no nlp item"
        fi
        i=$((i + 1))
    done

    log "[MISS] no new native query. raw=$RAW_FILE"
    return 1
}

run_probe() {
    local start_ts

    : > "$LOG_FILE"
    : > "$RAW_FILE"
    log "停止本项目客户端，恢复原生 wakeup.sh，启动/恢复 mipns-xiaomi"
    stop_project_clients
    restore_hook
    start_mipns

    start_ts=$(date +%s)
    log "准备触发小米原生 ASR。看到 [SPEAK NOW] 后请直接说一句追问，不要说小爱同学。"
    log "[SPEAK NOW] ${AI_DURATION}s 内说话"
    call_ai_service_asr >> "$LOG_FILE" 2>&1 &
    poll_native_result "$start_ts"
}

run_file_probe() {
    local start_ts
    local ret

    : > "$LOG_FILE"
    : > "$RAW_FILE"
    log "停止本项目客户端，恢复原生 wakeup.sh，启动/恢复 mipns-xiaomi"
    stop_project_clients
    restore_hook
    start_mipns

    log "准备录音。看到 [SPEAK NOW] 后请直接说一句追问，不要说小爱同学。"
    log "[SPEAK NOW] 开始本地 VAD 录音"
    SILENCE_LIMIT=2 SPEECH_THRESHOLD=180 "$VAD_SCRIPT" continue 8 >> "$LOG_FILE" 2>&1
    ret=$?
    if [ "$ret" -ne 0 ] || [ ! -f "$VOICE_FILE" ]; then
        log "[FAIL] VAD 录音失败 ret=$ret"
        return 1
    fi

    log "[REC] file=$VOICE_FILE size=$(wc -c < "$VOICE_FILE" 2>/dev/null)"
    start_ts=$(date +%s)
    call_ai_service_audio_file "$VOICE_FILE" >> "$LOG_FILE" 2>&1 &
    poll_native_result "$start_ts"
}

case "$1" in
    run)
        run_probe
        ;;
    file)
        run_file_probe
        ;;
    list)
        echo "--- ubus mibrain ---"
        ubus -v list mibrain
        ;;
    raw)
        ubus -t 2 call mibrain nlp_result_get
        ;;
    log)
        tail -f "$LOG_FILE" "$RAW_FILE"
        ;;
    *)
        echo "Usage: $0 {run|file|list|raw|log}"
        echo "Env: AI_DURATION=5 POLL_SECONDS=12 NLP_EXECUTE=0 TTS_ENABLE=0"
        exit 1
        ;;
esac
