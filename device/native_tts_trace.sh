#!/bin/sh
#
# Trace Xiaomi native TTS playback path.
#
# Use this only while reproducing a single utterance. It records:
# - ubus traffic
# - strace of mibrain_service and mediaplayer
# - /tmp/tts file changes
#

TRACE_DIR="${TRACE_DIR:-/tmp/native_tts_trace}"
POLL_INTERVAL="${POLL_INTERVAL:-0.1}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

stop_trace() {
    for f in "$TRACE_DIR"/*.pid; do
        [ -f "$f" ] || continue
        pid=$(cat "$f" 2>/dev/null)
        [ -n "$pid" ] && kill "$pid" 2>/dev/null
    done
    killall strace 2>/dev/null
}

watch_tts_dir() {
    while true; do
        {
            echo "===== $(date '+%H:%M:%S.%N') ====="
            ls -l /tmp/tts 2>/dev/null
        } >> "$TRACE_DIR/poll.log"
        sleep "$POLL_INTERVAL"
    done
}

start_trace() {
    stop_trace
    rm -rf "$TRACE_DIR"
    mkdir -p "$TRACE_DIR"

    log "trace dir: $TRACE_DIR"

    ubus monitor > "$TRACE_DIR/ubus_monitor.log" 2>&1 &
    echo $! > "$TRACE_DIR/ubus_monitor.pid"

    mpid=$(pidof mediaplayer 2>/dev/null | awk '{print $1}')
    if [ -n "$mpid" ]; then
        strace -ff -tt -s 512 \
            -e trace=process,execve,open,openat,access,stat,connect,sendto,recvfrom,write \
            -o "$TRACE_DIR/strace_mediaplayer" \
            -p "$mpid" >/dev/null 2>&1 &
        echo $! > "$TRACE_DIR/strace_mediaplayer.pid"
        log "attached mediaplayer pid=$mpid"
    else
        log "mediaplayer pid not found"
    fi

    bpid=$(pidof mibrain_service 2>/dev/null | awk '{print $1}')
    if [ -n "$bpid" ]; then
        strace -ff -tt -s 512 \
            -e trace=process,execve,open,openat,access,stat,connect,sendto,recvfrom,write \
            -o "$TRACE_DIR/strace_mibrain_service" \
            -p "$bpid" >/dev/null 2>&1 &
        echo $! > "$TRACE_DIR/strace_mibrain_service.pid"
        log "attached mibrain_service pid=$bpid"
    else
        log "mibrain_service pid not found"
    fi

    watch_tts_dir &
    echo $! > "$TRACE_DIR/poll.pid"

    log "started. Reproduce one utterance now, then run: sh /data/native_tts_trace.sh stop"
}

case "$1" in
    start)
        start_trace
        ;;
    stop)
        stop_trace
        log "stopped. Logs:"
        ls -l "$TRACE_DIR" 2>/dev/null
        ;;
    show)
        echo "--- ubus key lines ---"
        grep -E 'mibrain|mediaplayer|qplayer|text_to_speech|player_play_url|player_play_operation|media_control|set_player|notify' "$TRACE_DIR/ubus_monitor.log" 2>/dev/null | tail -120
        echo "--- poll key lines ---"
        grep -E 'tts_|total|\.mp3|\.wav' "$TRACE_DIR/poll.log" 2>/dev/null | tail -160
        echo "--- strace key lines ---"
        grep -hE 'tts_|/tmp/tts|text_to_speech|player_play_url|player_play_operation|media_control|execve|connect|sendto|write' "$TRACE_DIR"/strace_* 2>/dev/null | tail -200
        ;;
    status)
        echo "--- pids ---"
        for f in "$TRACE_DIR"/*.pid; do
            [ -f "$f" ] && echo "$(basename "$f") $(cat "$f")"
        done
        echo "--- files ---"
        ls -l "$TRACE_DIR" 2>/dev/null
        ;;
    *)
        echo "Usage: $0 {start|stop|show|status}"
        exit 1
        ;;
esac
