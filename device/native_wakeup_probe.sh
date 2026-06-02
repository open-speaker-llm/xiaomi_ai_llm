#!/bin/sh
#
# 小米原生唤醒探针（实验）
#
# 目的:
#   临时复用 /usr/bin/mipns-xiaomi + /usr/share/xiaomi/wakeup_model.bin，
#   通过 bind-mount 包装 /bin/wakeup.sh 观察原生唤醒事件。
#
# 用法:
#   sh /data/native_wakeup_probe.sh start   # 开始实验
#   sh /data/native_wakeup_probe.sh log     # 查看事件日志
#   sh /data/native_wakeup_probe.sh status  # 查看状态
#   sh /data/native_wakeup_probe.sh stop    # 停止并恢复
#
# 注意:
#   默认不透传原始 wakeup.sh，减少原生小爱抢答/提示音副作用。
#   如需透传原生动作，可设置 NATIVE_WAKEUP_PASSTHROUGH=1。

LOG_FILE="${LOG_FILE:-/tmp/native_wakeup_events.log}"
ORIG_WAKEUP="/tmp/wakeup.sh.orig"
HOOK_WAKEUP="/tmp/wakeup.sh.hook"
MIPNS_CONF="/usr/share/xiaomi/xaudio_engine.conf"

log() { echo "[$(date +%H:%M:%S)] $*"; }

stop_our_assistant() {
    killall kws 2>/dev/null
    killall tail 2>/dev/null
    killall curl 2>/dev/null
    killall aplay 2>/dev/null
    killall arecord 2>/dev/null
    ps | grep -E 'stream_client.sh|wake_monitor.sh|vad_record.sh' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
    rm -f /tmp/stream_fifo
}

install_hook() {
    if ! mount | grep -q ' on /bin/wakeup.sh '; then
        cp /bin/wakeup.sh "$ORIG_WAKEUP"
    fi

    cat > "$HOOK_WAKEUP" << 'EOF'
#!/bin/sh
LOG_FILE="${LOG_FILE:-/tmp/native_wakeup_events.log}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"
{
    echo "[$(date '+%H:%M:%S')] wakeup.sh $*"
} >> "$LOG_FILE"

case "$1" in
    WuW|WuW_first|WuW_oneshot|ready|noangle|bf)
        echo "[$(date '+%H:%M:%S')] NATIVE_WAKE_EVENT args=$*" >> "$LOG_FILE"
        ;;
esac

if [ "$NATIVE_WAKEUP_PASSTHROUGH" = "1" ] && [ -x "$ORIG_WAKEUP" ]; then
    exec "$ORIG_WAKEUP" "$@"
fi
exit 0
EOF
    chmod +x "$HOOK_WAKEUP"
    mount --bind "$HOOK_WAKEUP" /bin/wakeup.sh
}

restore_hook() {
    if mount | grep -q ' on /bin/wakeup.sh '; then
        umount /bin/wakeup.sh 2>/dev/null
    fi
}

start_mipns() {
    if pidof mipns-xiaomi >/dev/null 2>&1; then
        killall -CONT mipns-xiaomi 2>/dev/null
    else
        /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" >/tmp/native_mipns.log 2>&1 &
    fi
}

stop_mipns() {
    killall -STOP mipns-xiaomi 2>/dev/null
}

case "$1" in
    start)
        : > "$LOG_FILE"
        log "停止当前 sherpa-onnx 助手进程"
        stop_our_assistant
        log "安装 /bin/wakeup.sh 探针"
        install_hook
        log "恢复/启动原生 mipns-xiaomi"
        start_mipns
        log "开始监听原生唤醒。请说原生唤醒词：小爱同学"
        log "事件日志: $LOG_FILE"
        ;;
    stop)
        log "冻结原生 mipns-xiaomi"
        stop_mipns
        log "恢复 /bin/wakeup.sh"
        restore_hook
        log "停止完成"
        ;;
    status)
        echo "--- mipns ---"
        ps | grep mipns | grep -v grep || true
        echo "--- hook ---"
        mount | grep ' /bin/wakeup.sh ' || true
        echo "--- log ---"
        ls -l "$LOG_FILE" 2>/dev/null || true
        ;;
    log)
        tail -f "$LOG_FILE"
        ;;
    *)
        echo "Usage: $0 {start|stop|status|log}"
        exit 1
        ;;
esac
