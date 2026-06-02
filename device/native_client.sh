#!/bin/sh
#
# 小米AI音箱 LLM 对话助手 — 原生唤醒版
#
# 使用小米原生 mipns-xiaomi + wakeup_model.bin 检测“小爱同学”，
# 只复用原生唤醒事件，不透传原生小爱后续流程。
#

SERVER="${SERVER:-http://192.168.8.150:8080}"
BACKEND="${BACKEND:-deepseek}"
VAD_SCRIPT="/data/vad_record.sh"
EVENT_LOG="/tmp/native_wakeup_events.log"
EVENT_FIFO="/tmp/native_wakeup_event.fifo"
ORIG_WAKEUP="/tmp/wakeup.sh.orig"
HOOK_WAKEUP="/tmp/wakeup.sh.native_hook"
MIPNS_CONF="/usr/share/xiaomi/xaudio_engine.conf"
FOLLOWUP_TIMEOUT="${FOLLOWUP_TIMEOUT:-6}"
FOLLOWUP_THRESHOLD="${FOLLOWUP_THRESHOLD:-220}"
FIRST_TURN_TIMEOUT="${FIRST_TURN_TIMEOUT:-8}"
STREAM_TIMEOUT="${STREAM_TIMEOUT:-180}"
ROUTE_TIMEOUT="${ROUTE_TIMEOUT:-80}"
WAKE_ACK_DELAY="${WAKE_ACK_DELAY:-0.5}"
POST_NATIVE_DELAY="${POST_NATIVE_DELAY:-3.0}"
POST_LLM_DELAY="${POST_LLM_DELAY:-1.0}"
WAKE_EVENT_MAX_AGE="${WAKE_EVENT_MAX_AGE:-2}"
WAKE_RESTORE_COOLDOWN="${WAKE_RESTORE_COOLDOWN:-2}"

LED_RGB="/sys/devices/i2c-1/1-003c/led_rgb"
LED_IDS="0 1 2 3 4 5 6 7 8 9 10 11"
LED_BLUE=16711680
IGNORE_WAKE_UNTIL=0

log() { echo "[$(date +%H:%M:%S)] $*"; }

led_set_all() {
    local color="$1"
    [ -w "$LED_RGB" ] || return 0
    for i in $LED_IDS; do
        echo "$i $color" > "$LED_RGB" 2>/dev/null
    done
}

led_on()  { led_set_all "$LED_BLUE"; }
led_off() { led_set_all 0; }

json_escape() {
    printf "%s" "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

setup_audio() {
    if [ ! -d /dev/snd ]; then
        mkdir -p /dev/snd
        mknod /dev/snd/controlC0 c 116 0 2>/dev/null
        mknod /dev/snd/pcmC0D0p c 116 16 2>/dev/null
        mknod /dev/snd/pcmC0D1p c 116 17 2>/dev/null
        mknod /dev/snd/pcmC0D0c c 116 24 2>/dev/null
        mknod /dev/snd/pcmC0D2c c 116 26 2>/dev/null
        mknod /dev/snd/timer   c 116 33 2>/dev/null
    fi
    amixer -c 0 sset 'Hard Mute' off 2>/dev/null
    amixer -c 0 sset 'Ch1' unmute 2>/dev/null
    amixer -c 0 sset 'Ch2' unmute 2>/dev/null
    amixer -c 0 sset 'Master' 224 2>/dev/null
}

stop_sherpa_client() {
    killall kws 2>/dev/null
    killall tail 2>/dev/null
    killall curl 2>/dev/null
    killall aplay 2>/dev/null
    killall arecord 2>/dev/null
    ps | grep -E 'stream_client.sh|wake_monitor.sh|vad_record.sh' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
    rm -f /tmp/stream_fifo
}

stop_existing_native_clients() {
    ps | awk '$5 == "sh" && $6 == "/data/native_client.sh" {print $1}' | while read pid; do
        [ "$pid" = "$$" ] && continue
        kill "$pid" 2>/dev/null
        sleep 0.1
        kill -9 "$pid" 2>/dev/null
    done
}

install_wakeup_hook() {
    if ! mount | grep -q ' on /bin/wakeup.sh '; then
        cp /bin/wakeup.sh "$ORIG_WAKEUP"
    fi

    cat > "$HOOK_WAKEUP" << 'EOF'
#!/bin/sh
EVENT_LOG="${EVENT_LOG:-/tmp/native_wakeup_events.log}"
EVENT_FIFO="${EVENT_FIFO:-/tmp/native_wakeup_event.fifo}"

echo "[$(date '+%H:%M:%S')] wakeup.sh $*" >> "$EVENT_LOG"

case "$1" in
    WuW|WuW_first|WuW_oneshot)
        echo "[$(date '+%H:%M:%S')] NATIVE_WAKE_EVENT args=$*" >> "$EVENT_LOG"
        if [ -x /tmp/wakeup.sh.orig ]; then
            /tmp/wakeup.sh.orig "$1" >/dev/null 2>&1 &
        fi
        killall -STOP mipns-xiaomi 2>/dev/null
        if [ -p "$EVENT_FIFO" ]; then
            event_ts=$(date +%s)
            ( echo "WuW $event_ts" > "$EVENT_FIFO" 2>/dev/null ) &
        fi
        ;;
    bf|noangle|ready)
        echo "[$(date '+%H:%M:%S')] NATIVE_WAKE_EVENT args=$*" >> "$EVENT_LOG"
        ;;
esac

exit 0
EOF
    chmod +x "$HOOK_WAKEUP"
    mount --bind "$HOOK_WAKEUP" /bin/wakeup.sh
}

restore_wakeup_hook() {
    if mount | grep -q ' on /bin/wakeup.sh '; then
        umount /bin/wakeup.sh 2>/dev/null
    fi
}

start_native_mipns() {
    if pidof mipns-xiaomi >/dev/null 2>&1; then
        killall -CONT mipns-xiaomi 2>/dev/null
    else
        /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" >/tmp/native_mipns.log 2>&1 &
    fi
}

send_and_play() {
    local session_id="$1"; local backend="$2"
    local voice_file="/tmp/voice.wav"
    if [ ! -f "$voice_file" ]; then
        log "[ERROR] 录音文件不存在"
        return 1
    fi
    local size; size=$(wc -c < "$voice_file")
    log "[SEND] ${size} bytes → ${SERVER} (session=$session_id, backend=$backend)"

    rm -f /tmp/stream_fifo
    mkfifo /tmp/stream_fifo 2>/dev/null || mknod /tmp/stream_fifo p 2>/dev/null

    curl -s --no-buffer -o /tmp/stream_fifo --max-time "$STREAM_TIMEOUT" \
        -F "file=@${voice_file}" \
        "${SERVER}/api/v1/stream/chat?session_id=${session_id}&backend=${backend}&speed=1.0&volume=1.8" &
    CURL_PID=$!

    aplay /tmp/stream_fifo 2>/dev/null &
    APLAY_PID=$!

    wait $CURL_PID 2>/dev/null
    wait $APLAY_PID 2>/dev/null

    log "[SPEAKING] 播放完成..."
    sleep "$POST_LLM_DELAY"
    rm -f /tmp/stream_fifo
    return 0
}

route_voice() {
    local voice_file="/tmp/voice.wav"
    local result_file="/tmp/native_route_result.env"

    if [ ! -f "$voice_file" ]; then
        log "[ERROR] 录音文件不存在"
        return 1
    fi

    curl -s --max-time "$ROUTE_TIMEOUT" \
        -F "file=@${voice_file}" \
        "${SERVER}/api/v1/route/asr" > "$result_file"

    ROUTE=$(sed -n 's/^ROUTE=//p' "$result_file" | head -1)
    ROUTE_TEXT=$(sed -n 's/^TEXT=//p' "$result_file" | head -1)
    ROUTE_REASON=$(sed -n 's/^REASON=//p' "$result_file" | head -1)

    [ -n "$ROUTE" ] || ROUTE="llm"
    [ -n "$ROUTE_TEXT" ] || return 1

    log "[ROUTE] text=$ROUTE_TEXT route=$ROUTE reason=$ROUTE_REASON"
    return 0
}

native_control() {
    local text="$1"
    local safe_text; safe_text=$(json_escape "$text")
    local req_id="native_control_$(date +%s)"
    local result_file="/tmp/native_control_result.json"

    log "[NATIVE] 转发小米原生控制: $text"
    ubus -t 30 call mibrain ai_service \
        "{\"bypass\":\"\",\"caller\":\"native_client\",\"duration\":0,\"id\":\"$req_id\",\"asr\":0,\"nlp\":1,\"tts\":1,\"asr_audio\":\"\",\"nlp_text\":\"$safe_text\",\"nlp_execute\":1,\"tts_text\":\"\",\"tts_type\":\"\",\"tts_vendor\":\"\",\"tts_volume\":80,\"tts_codec\":\"mp3\",\"tts_save\":0,\"tts_play\":1}" \
        > "$result_file" 2>&1
    ret=$?
    if [ $ret -ne 0 ]; then
        log "[NATIVE] 执行失败 ret=$ret"
        cat "$result_file"
        return $ret
    fi
    log "[NATIVE] 已交给小米原生链路"
    return 0
}

send_text_and_play() {
    local session_id="$1"; local backend="$2"; local text="$3"
    log "[SEND] text → ${SERVER} (session=$session_id, backend=$backend)"

    rm -f /tmp/stream_fifo
    mkfifo /tmp/stream_fifo 2>/dev/null || mknod /tmp/stream_fifo p 2>/dev/null

    curl -s --no-buffer -o /tmp/stream_fifo --max-time "$STREAM_TIMEOUT" \
        -F "message=${text}" \
        -F "session_id=${session_id}" \
        -F "backend=${backend}" \
        -F "speed=1.0" \
        -F "volume=1.8" \
        "${SERVER}/api/v1/stream/text_chat" &
    CURL_PID=$!

    aplay /tmp/stream_fifo 2>/dev/null &
    APLAY_PID=$!

    wait $CURL_PID 2>/dev/null
    wait $APLAY_PID 2>/dev/null

    log "[SPEAKING] 播放完成..."
    sleep "$POST_LLM_DELAY"
    rm -f /tmp/stream_fifo
    return 0
}

handle_dialog() {
    local session_id="${BACKEND}_native_$(date +%s)"
    local turn=1
    local suppress_wake_after_dialog=0

    log "[WAKING] 原生唤醒 → backend=$BACKEND session=$session_id"
    led_on
    sleep "$WAKE_ACK_DELAY"

    while true; do
        log ""
        if [ $turn -eq 1 ]; then
            log "[LISTEN] 请说话..."
            sh "$VAD_SCRIPT" first "$FIRST_TURN_TIMEOUT"
            ret=$?
            if [ $ret -eq 124 ]; then
                log "[TIMEOUT] 唤醒后 ${FIRST_TURN_TIMEOUT}s 无语音，退出对话"
                break
            fi
        else
            log "[FOLLOWUP] ${FOLLOWUP_TIMEOUT}s 内可继续追问..."
            SPEECH_THRESHOLD="$FOLLOWUP_THRESHOLD" sh "$VAD_SCRIPT" continue "$FOLLOWUP_TIMEOUT"
            ret=$?
            if [ $ret -eq 124 ]; then
                log "[TIMEOUT] ${FOLLOWUP_TIMEOUT}s 无语音，退出对话"
                break
            fi
        fi

        if [ $ret -ne 0 ]; then
            log "[LISTEN] 录音失败，退出对话 ret=$ret"
            break
        fi

        log "[TURN $turn] 发送到服务器做 ASR 门控..."
        if ! route_voice; then
            log "[ROUTE] 失败，退出对话"
            break
        fi

        if [ "$ROUTE" = "native" ]; then
            native_control "$ROUTE_TEXT"
            sleep "$POST_NATIVE_DELAY"
            log "[NATIVE] 控制命令完成，退出对话"
            suppress_wake_after_dialog=1
            break
        elif [ "$ROUTE" = "empty" ]; then
            log "[ROUTE] 空文本，退出对话"
            break
        else
            send_text_and_play "$session_id" "$BACKEND" "$ROUTE_TEXT"
        fi

        log "[TURN $turn] 播放完成"
        turn=$((turn + 1))
    done

    led_off
    if [ "$suppress_wake_after_dialog" -eq 1 ]; then
        IGNORE_WAKE_UNTIL=$(($(date +%s) + WAKE_RESTORE_COOLDOWN))
    fi
    killall -CONT mipns-xiaomi 2>/dev/null
    log "[IDLE] 等待原生唤醒词：小爱同学"
}

cleanup() {
    led_off
    restore_wakeup_hook
    killall -STOP mipns-xiaomi 2>/dev/null
    rm -f "$EVENT_FIFO"
}

case "$1" in
    stop)
        stop_existing_native_clients
        cleanup
        exit 0
        ;;
esac

stop_existing_native_clients
trap cleanup INT TERM EXIT

log "=== 小米AI音箱 LLM 对话助手 (native wakeup) ==="
log "Server: $SERVER"
log "Backend: $BACKEND"

setup_audio
stop_sherpa_client
rm -f "$EVENT_FIFO"
mkfifo "$EVENT_FIFO" 2>/dev/null || mknod "$EVENT_FIFO" p 2>/dev/null
: > "$EVENT_LOG"

curl -s -o /dev/null -m 2 "$SERVER/" && log "服务器连接正常" || log "服务器无法连接"

install_wakeup_hook
start_native_mipns

log "[IDLE] 等待原生唤醒词：小爱同学"
while true; do
    if read event ts < "$EVENT_FIFO"; then
        [ "$event" = "WuW" ] || continue
        now=$(date +%s)
        if [ "$now" -lt "$IGNORE_WAKE_UNTIL" ]; then
            remain=$((IGNORE_WAKE_UNTIL - now))
            log "[IDLE] 忽略冷却期唤醒事件 remain=${remain}s"
            continue
        fi
        if [ -n "$ts" ]; then
            age=$((now - ts))
            if [ "$age" -gt "$WAKE_EVENT_MAX_AGE" ]; then
                log "[IDLE] 忽略过期唤醒事件 age=${age}s"
                continue
            fi
        fi
        handle_dialog
    fi
done
