#!/bin/sh
#
# Trace Xiaomi native wake -> ASR/NLP path for one utterance.
#

TRACE_DIR="${TRACE_DIR:-/tmp/native_wake_asr_trace}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"
HOOK_WAKEUP="${HOOK_WAKEUP:-/tmp/wakeup.sh.trace}"
MIPNS_CONF="${MIPNS_CONF:-/usr/share/xiaomi/xaudio_engine.conf}"
POLL_INTERVAL="${POLL_INTERVAL:-0.2}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

stop_background() {
    for f in "$TRACE_DIR"/*.pid; do
        [ -f "$f" ] || continue
        pid=$(cat "$f" 2>/dev/null)
        [ -n "$pid" ] && kill "$pid" 2>/dev/null
    done
    killall strace 2>/dev/null
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

install_wakeup_trace_hook() {
    restore_hook
    ensure_original_wakeup

    cat > "$HOOK_WAKEUP" << 'EOF'
#!/bin/sh
TRACE_DIR="${TRACE_DIR:-/tmp/native_wake_asr_trace}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"
mkdir -p "$TRACE_DIR"
echo "[$(date '+%H:%M:%S.%N')] wakeup.sh $*" >> "$TRACE_DIR/wakeup_events.log"
if [ -x "$ORIG_WAKEUP" ]; then
    exec "$ORIG_WAKEUP" "$@"
fi
exit 0
EOF
    chmod +x "$HOOK_WAKEUP"
    mount --bind "$HOOK_WAKEUP" /bin/wakeup.sh
}

stop_project_clients() {
    killall curl 2>/dev/null
    killall aplay 2>/dev/null
    killall arecord 2>/dev/null
    ps | grep -E 'native_first_client.sh|native_first_cl|native_client.sh|stream_client.sh|wake_monitor.sh|vad_record.sh|native_first_observer.sh|native_followup_probe.sh' \
        | grep -v grep | awk '{print $1}' | xargs -r kill -9 2>/dev/null
    rm -f /tmp/native_first_busy /tmp/native_first_player_frozen /tmp/stream_fifo
}

start_mipns() {
    if pidof mipns-xiaomi >/dev/null 2>&1; then
        killall -CONT mipns-xiaomi 2>/dev/null
    else
        /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" >/tmp/native_mipns.log 2>&1 &
    fi
}

watch_state() {
    while true; do
        {
            echo "===== $(date '+%H:%M:%S.%N') ====="
            echo "--- ps ---"
            ps | grep -E 'mipns|mibrain|mediaplayer|xiaomi|aivs|ubus' | grep -v grep
            echo "--- tmp interest ---"
            ls -lt /tmp /tmp/tts 2>/dev/null | head -80
            echo "--- nlp_result_get ---"
            ubus -t 1 call mibrain nlp_result_get 2>&1
        } >> "$TRACE_DIR/state_poll.log"
        sleep "$POLL_INTERVAL"
    done
}

attach_strace() {
    local name="$1"
    local pid="$2"

    [ -n "$pid" ] || return 0
    strace -ff -tt -s 512 \
        -e trace=process,execve,open,openat,access,stat,connect,sendto,recvfrom,read,write,ioctl \
        -o "$TRACE_DIR/strace_$name" \
        -p "$pid" >/dev/null 2>&1 &
    echo $! > "$TRACE_DIR/strace_$name.pid"
    log "attached $name pid=$pid"
}

start_trace() {
    stop_background
    rm -rf "$TRACE_DIR"
    mkdir -p "$TRACE_DIR"

    log "trace dir: $TRACE_DIR"
    log "stop project clients, restore native path"
    stop_project_clients
    restore_hook
    start_mipns
    install_wakeup_trace_hook

    ubus monitor > "$TRACE_DIR/ubus_monitor.log" 2>&1 &
    echo $! > "$TRACE_DIR/ubus_monitor.pid"

    attach_strace "mipns" "$(pidof mipns-xiaomi 2>/dev/null | awk '{print $1}')"
    attach_strace "mibrain_service" "$(pidof mibrain_service 2>/dev/null | awk '{print $1}')"
    attach_strace "mediaplayer" "$(pidof mediaplayer 2>/dev/null | awk '{print $1}')"

    watch_state &
    echo $! > "$TRACE_DIR/state_poll.pid"

    log "started. Say one native command now, e.g. 小爱同学，现在几点. Then run stop."
}

stop_trace() {
    stop_background
    restore_hook
    killall -CONT mipns-xiaomi 2>/dev/null
    killall -CONT mediaplayer 2>/dev/null
    log "stopped. Logs:"
    ls -lh "$TRACE_DIR" 2>/dev/null
}

show_trace() {
    echo "--- wakeup events ---"
    cat "$TRACE_DIR/wakeup_events.log" 2>/dev/null
    echo "--- ubus key lines ---"
    grep -E 'mibrain|mipns|wakeup|voice|asr|nlp|aivs|mediaplayer|player|event_notify|ai_service' "$TRACE_DIR/ubus_monitor.log" 2>/dev/null | tail -200
    echo "--- nlp snapshots ---"
    grep -E 'nlp_result_get|timestamp|query|domain|to_speak|asr' "$TRACE_DIR/state_poll.log" 2>/dev/null | tail -160
    echo "--- strace key lines ---"
    grep -hE 'wakeup|mibrain|aivs|asr|nlp|voice|audio|speech|/tmp|connect|sendto|recvfrom|execve|open|write' "$TRACE_DIR"/strace_* 2>/dev/null | tail -240
}

restart_client() {
    restore_hook
    killall -CONT mipns-xiaomi 2>/dev/null
    killall -CONT mediaplayer 2>/dev/null
    rm -f /tmp/native_first_busy /tmp/native_first_player_frozen /tmp/stream_fifo
    SERVER="${SERVER:-http://192.168.8.150:8080}" BACKEND="${BACKEND:-deepseek}" \
        start-stop-daemon -S -b -x /data/native_first_client.sh
}

case "$1" in
    start)
        start_trace
        ;;
    stop)
        stop_trace
        ;;
    show)
        show_trace
        ;;
    status)
        echo "--- trace files ---"
        ls -lh "$TRACE_DIR" 2>/dev/null
        echo "--- pids ---"
        for f in "$TRACE_DIR"/*.pid; do
            [ -f "$f" ] && echo "$(basename "$f") $(cat "$f")"
        done
        echo "--- hook ---"
        mount | grep ' /bin/wakeup.sh ' || true
        ;;
    restart-client)
        restart_client
        ;;
    *)
        echo "Usage: $0 {start|stop|show|status|restart-client}"
        exit 1
        ;;
esac
