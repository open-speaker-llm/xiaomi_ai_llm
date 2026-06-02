#!/bin/sh
#
# Native-first observation mode.
#
# This does not stop Xiaomi's native ASR/NLP path. It wraps /bin/wakeup.sh,
# passes events through to the original script, and records enough side data to
# decide whether a native-first + LLM fallback flow is viable.
#

LOG_FILE="${LOG_FILE:-/tmp/native_first_observer.log}"
EVENT_LOG="${EVENT_LOG:-/tmp/native_first_wakeup_events.log}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"
HOOK_WAKEUP="${HOOK_WAKEUP:-/tmp/wakeup.sh.native_first_observer}"
MIPNS_CONF="${MIPNS_CONF:-/usr/share/xiaomi/xaudio_engine.conf}"
OBSERVE_SECONDS="${OBSERVE_SECONDS:-12}"
SIDE_RECORD_TIMEOUT="${SIDE_RECORD_TIMEOUT:-8}"
SIDE_RECORD_SILENCE="${SIDE_RECORD_SILENCE:-2}"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG_FILE"; }

stop_our_assistants() {
    killall kws 2>/dev/null
    killall tail 2>/dev/null
    killall curl 2>/dev/null
    killall aplay 2>/dev/null
    killall arecord 2>/dev/null
    ps | grep -E 'stream_client.sh|wake_monitor.sh|vad_record.sh|native_client.sh' | grep -v grep | awk '{print $1}' | xargs -r kill -9 2>/dev/null
    rm -f /tmp/stream_fifo /tmp/native_wakeup_event.fifo
}

restore_hook() {
    while mount | grep -q ' on /bin/wakeup.sh '; do
        umount /bin/wakeup.sh 2>/dev/null
        sleep 0.1
    done
}

ensure_original_wakeup() {
    if [ -f "$ORIG_WAKEUP" ] && grep -q 'play_wakeup' "$ORIG_WAKEUP" 2>/dev/null; then
        return 0
    fi
    cp /bin/wakeup.sh "$ORIG_WAKEUP"
}

install_hook() {
    restore_hook
    ensure_original_wakeup

    cat > "$HOOK_WAKEUP" << 'EOF'
#!/bin/sh
LOG_FILE="${LOG_FILE:-/tmp/native_first_observer.log}"
EVENT_LOG="${EVENT_LOG:-/tmp/native_first_wakeup_events.log}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"

echo "[$(date '+%H:%M:%S')] wakeup.sh $*" >> "$EVENT_LOG"

case "$1" in
    WuW|WuW_first|WuW_oneshot)
        echo "[$(date '+%H:%M:%S')] NATIVE_WAKE_EVENT args=$*" >> "$EVENT_LOG"
        /data/native_first_observer.sh observe "$1" >> "$LOG_FILE" 2>&1 &
        ;;
    bf|bf_end|noangle|noangle_end|ready|think|multirounds)
        echo "[$(date '+%H:%M:%S')] NATIVE_WAKE_EVENT args=$*" >> "$EVENT_LOG"
        ;;
esac

if [ -x "$ORIG_WAKEUP" ]; then
    exec "$ORIG_WAKEUP" "$@"
fi
exit 0
EOF
    chmod +x "$HOOK_WAKEUP"
    mount --bind "$HOOK_WAKEUP" /bin/wakeup.sh
}

start_mipns() {
    if pidof mipns-xiaomi >/dev/null 2>&1; then
        killall -CONT mipns-xiaomi 2>/dev/null
    else
        /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" >/tmp/native_mipns.log 2>&1 &
    fi
}

observe_session() {
    local event="$1"
    local sid; sid=$(date +%s)
    local raw_file="/tmp/native_first_nlp_${sid}.log"
    local voice_file="/tmp/native_first_voice_${sid}.wav"

    echo "[$(date '+%H:%M:%S')] [SESSION $sid] wake=$event start"
    echo "[$(date '+%H:%M:%S')] [SESSION $sid] before nlp_result_get"
    ubus -t 2 call mibrain nlp_result_get

    (
        SILENCE_LIMIT="$SIDE_RECORD_SILENCE" sh /data/vad_record.sh first "$SIDE_RECORD_TIMEOUT"
        ret=$?
        if [ $ret -eq 0 ] && [ -f /tmp/voice.wav ]; then
            cp /tmp/voice.wav "$voice_file" 2>/dev/null
            echo "[$(date '+%H:%M:%S')] [SESSION $sid] side_record ok file=$voice_file size=$(wc -c < "$voice_file" 2>/dev/null)"
        else
            echo "[$(date '+%H:%M:%S')] [SESSION $sid] side_record ret=$ret"
        fi
    ) &
    rec_pid=$!

    i=0
    while [ $i -lt "$OBSERVE_SECONDS" ]; do
        sleep 1
        echo "[$(date '+%H:%M:%S')] [SESSION $sid] poll=$((i + 1))"
        ubus -t 2 call mibrain nlp_result_get | tee -a "$raw_file"
        i=$((i + 1))
    done

    wait "$rec_pid" 2>/dev/null
    echo "[$(date '+%H:%M:%S')] [SESSION $sid] end raw=$raw_file"
}

case "$1" in
    start)
        : > "$LOG_FILE"
        : > "$EVENT_LOG"
        log "停止本项目助手进程，但保留/恢复小米原生 mipns"
        stop_our_assistants
        log "安装 native-first observer hook"
        install_hook
        log "恢复/启动 mipns-xiaomi"
        start_mipns
        log "观察模式已启动。请测试：开灯 / 现在几点 / 开放问答"
        log "主日志: $LOG_FILE"
        log "唤醒事件: $EVENT_LOG"
        ;;
    stop)
        log "停止观察模式，恢复 /bin/wakeup.sh，冻结 mipns-xiaomi"
        restore_hook
        killall -STOP mipns-xiaomi 2>/dev/null
        ;;
    status)
        echo "--- mipns ---"
        ps | grep mipns | grep -v grep || true
        echo "--- hook ---"
        mount | grep ' /bin/wakeup.sh ' || true
        echo "--- logs ---"
        ls -l "$LOG_FILE" "$EVENT_LOG" 2>/dev/null || true
        ;;
    log)
        tail -f "$LOG_FILE"
        ;;
    observe)
        observe_session "$2"
        ;;
    *)
        echo "Usage: $0 {start|stop|status|log|observe}"
        exit 1
        ;;
esac
