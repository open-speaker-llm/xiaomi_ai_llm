#!/bin/sh
#
# Manual native ASR reopen test.
# Run on the speaker, speak during the wait window, then inspect the printed log.
#

MODE="${1:-pns6}"
WAIT_SECONDS="${WAIT_SECONDS:-10}"
PROBE="${PROBE:-/data/native_reopen_probe.sh}"
CONFIG_FILE="${CONFIG_FILE:-/data/native_first.env}"
CLIENT_LOG="${CLIENT_LOG:-/tmp/native_first_client.log}"
LOG_FILE="${LOG_FILE:-/tmp/native_reopen_manual_${MODE}.log}"

stop_client() {
    ps | grep "[n]ative_first_client.sh" | while read pid rest; do
        kill -9 "$pid" 2>/dev/null
    done

    while mount | grep -q " on /bin/wakeup.sh "; do
        umount /bin/wakeup.sh 2>/dev/null || break
        sleep 0.1
    done
}

start_client() {
    CONFIG_FILE="$CONFIG_FILE" sh /data/native_first_client.sh > "$CLIENT_LOG" 2>&1 &
}

run_probe() {
    case "$MODE" in
        pns6)
            LOG_FILE="$LOG_FILE" WAIT_SECONDS="$WAIT_SECONDS" sh "$PROBE" pns 6 manual_followup
            ;;
        pns4)
            LOG_FILE="$LOG_FILE" WAIT_SECONDS="$WAIT_SECONDS" sh "$PROBE" pns 4 pre_multirounds
            ;;
        oneshot)
            LOG_FILE="$LOG_FILE" WAIT_SECONDS="$WAIT_SECONDS" sh "$PROBE" oneshot true
            ;;
        multirounds)
            LOG_FILE="$LOG_FILE" WAIT_SECONDS="$WAIT_SECONDS" sh "$PROBE" wakeup_multirounds
            ;;
        *)
            echo "Usage: $0 [pns6|pns4|oneshot|multirounds]"
            return 2
            ;;
    esac
}

echo "=== native reopen manual test: mode=$MODE wait=${WAIT_SECONDS}s ==="
echo "说话窗口出现后，不要喊小爱同学，直接说：Mac电脑怎么重启"

chmod +x "$PROBE" 2>/dev/null
stop_client
sleep 1
run_probe
ret=$?
start_client
sleep 2

echo "=== client restored ==="
tail -n 20 "$CLIENT_LOG" 2>/dev/null
echo "=== probe log: $LOG_FILE ==="
tail -n 120 "$LOG_FILE" 2>/dev/null
exit "$ret"
