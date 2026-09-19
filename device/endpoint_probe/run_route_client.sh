#!/bin/sh
# Temporary client replacement via /tmp process, never overwrite /data.
set -eu
D=/tmp/xiaomi_native_route
original=/data/native_first_client.sh
trial=$D/native_first_client.sh
ORIGINAL_ROUTE_SHA256=70a7012f2c68c7ebc8e545d9481845068406a476dc4cff7e68808fe671f8f184
ROUTE_INSTRUCTION_LOG=/tmp/mico_aivs_lab/instruction.log
. "$D/native_route_restore.sh"
hash() { sha256sum "$1" | awk '{print $1}'; }
stop_client() {
    expected=$1
    pid=$(cat /tmp/native_first_client.pid 2>/dev/null || :)
    case "$pid" in '') [ ! -e /tmp/native_first_client.pid ]; return $?;; 0|1|*[!0-9]*) return 1;; esac
    cmd=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null || :)
    if [ -z "$cmd" ] && ! kill -0 "$pid" 2>/dev/null; then return 0; fi
    [ "$cmd" = "sh $expected " ] || return 1
    kill -TERM "$pid" 2>/dev/null || :
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        cmd=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null || :)
        [ "$cmd" = "sh $expected " ] || return 1
        kill -KILL "$pid" || return 1
        count=0
        while [ -r "/proc/$pid/cmdline" ] && [ -n "$(tr '\000' ' ' < "/proc/$pid/cmdline")" ]; do
            count=$((count+1)); [ "$count" -lt 25 ] || return 1; sleep 0.1
        done
    fi
}
stop_route_client() {
    pid=$(cat /tmp/native_first_client.pid 2>/dev/null || :)
    case "$pid" in '') [ ! -e /tmp/native_first_client.pid ]; return $?;; 0|1|*[!0-9]*) return 1;; esac
    cmd=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null || :)
    case "$cmd" in
        "sh $trial ") stop_client "$trial";;
        "sh $original ") stop_client "$original";;
        '') ! kill -0 "$pid" 2>/dev/null;;
        *) return 1;;
    esac
}
launch_client() {
    path=$1 log=$2
    (trap '' HUP; LOG_FILE="$log" sh "$path") > "$D/launch.log" 2>&1 </dev/null &
    child=$!
    count=0
    while [ "$count" -lt 25 ]; do
        sleep 1; count=$((count+1))
        kill -0 "$child" 2>/dev/null || return 1
        if [ "$(cat /tmp/native_first_client.pid 2>/dev/null)" = "$child" ] && grep -q '\[IDLE\].*等待原生唤醒词' "$log"; then
            echo CLIENT_READY pid=$child;return 0
        fi
    done
    return 1
}
restore() { /tmp/xiaomi_native_wake_probe/native_restore_guard route; }
case "${1:-}" in
setup)
    restore_seconds=${NATIVE_ROUTE_RESTORE_SECONDS:-480}
    case "$restore_seconds" in ''|*[!0-9]*) exit 2;; esac
    [ "${#restore_seconds}" -le 5 ] && [ "$restore_seconds" -ge 60 ] && [ "$restore_seconds" -le 86520 ]
    [ -x /tmp/xiaomi_native_wake_probe/native_restore_guard ]
    # Client initialization calls native_asr.sh start. Install the client BEFORE
    # the probe overlay, otherwise that manager can remove the diagnostic layer.
    for init in /etc/init.d/pns /etc/init.d/mico_aivs_lab; do
        if grep -q XIAOMI_NATIVE_WAKE_OBSERVE "$init"; then
            echo 'Start the temporary client before installing the wake probe' >&2
            exit 2
        fi
    done
    sh /data/native_asr.sh status
    test ! -e /tmp/native_first_busy
    test ! -e "$D/armed"
    : "${EXPECTED_ROUTE_CLIENT_SHA256:?}"
    [ "$(hash "$trial")" = "$EXPECTED_ROUTE_CLIENT_SHA256" ]
    [ "$(hash "$original")" = 70a7012f2c68c7ebc8e545d9481845068406a476dc4cff7e68808fe671f8f184 ]
    umask 077
    cp /tmp/native_first_client.log "$D/client.before.log"
    cp /tmp/native_first_events.log "$D/events.before.log"
    token=$(cat /proc/sys/kernel/random/uuid)
    printf '%s\n' "$token" > "$D/armed"
    printf '%s\n' "$token" > "$D/timer.armed"
    now=$(awk '{print int($1)}' /proc/uptime)
    printf '%s\n' "$((now + restore_seconds))" > "$D/timer.deadline"
    (
        trap '' HUP
        printf '%s\n' "$token" > "$D/timer.ready"
        sleep "$restore_seconds"
        [ "$(cat "$D/armed" 2>/dev/null)" != "$token" ] || sh "$D/run_route_client.sh" restore
    ) > "$D/timer.log" 2>&1 </dev/null &
    timer=$!
    sleep 1;kill -0 "$timer";[ "$(cat "$D/timer.ready")" = "$token" ]
    trap restore EXIT
    stop_client "$original"
    launch_client "$trial" "$D/client.log"
    trap - EXIT
    ;;
restore) restore;;
_restore) [ "${NATIVE_RESTORE_GUARDED:-}" = 1 ] || exit 2; route_restore_legacy;;
*) exit 2;;
esac
