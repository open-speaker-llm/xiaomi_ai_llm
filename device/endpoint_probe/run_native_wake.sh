#!/bin/sh
# Temporary one-shot diagnostic. Loading alone does not enable endpoint control;
# native_wake_watch endpoint additionally requires a preloaded verified helper.
set -eu
D=/tmp/xiaomi_native_wake_probe
TAG=XIAOMI_NATIVE_WAKE_OBSERVE
hash() { sha256sum "$1" | awk '{print $1}'; }
restore() {
    stopped=${1:-0}
    if [ "$stopped" = 1 ]; then
        [ -z "$(pidof mipns-xiaomi mico_aivs_lab 2>/dev/null || :)" ] || return 1
    fi
    # Ask the current supervisor to stop, then wait for its kernel lock to be
    # released before touching native service overlays. No PID-file signalling.
    if [ -x "$D/native_wake_session" ]; then
        NATIVE_WAKE_SESSION_DIR="$D" sh "$D/run_native_wake_session.sh" stop || return 1
    fi
    changed=0
    for name in pns mico_aivs_lab; do
        target=/etc/init.d/$name
        if grep -q "$TAG" "$target"; then
            [ "$(hash "$target")" = "$(cat "$D/$name.overlay.sha")" ] || return 1
            umount "$target"
            [ "$(hash "$target")" = "$(cat "$D/$name.before.sha")" ] || return 1
            changed=1
        fi
    done
    rm -f "$D/timer.armed" "$D/native-wake.state"
    if [ "$changed" = 1 ] && [ "$stopped" != 1 ]; then
        /etc/init.d/mico_aivs_lab restart
        /etc/init.d/pns restart
    fi
}
case "${1:-}" in
restore) "$D/native_restore_guard" native;;
_restore) [ "${NATIVE_RESTORE_GUARDED:-}" = 1 ] || exit 2; restore;;
restore-stopped) [ "${NATIVE_RESTORE_GUARDED:-}" = 1 ] || exit 2; restore 1;;
setup)
    restore_seconds=${NATIVE_WAKE_RESTORE_SECONDS:-300}
    case "$restore_seconds" in ''|*[!0-9]*) exit 2;; esac
    [ "${#restore_seconds}" -le 5 ] && [ "$restore_seconds" -ge 60 ] && [ "$restore_seconds" -le 86520 ]
    [ -x "$D/native_restore_guard" ]
    [ ! -e /tmp/native_first_busy ]
    [ ! -e "$D/timer.armed" ]
    sh /data/native_asr.sh status
    : "${EXPECTED_WAKE_PROBE_SHA256:?}"
    [ "$(hash "$D/native_wake_probe.so")" = "$EXPECTED_WAKE_PROBE_SHA256" ]
    [ "$(hash /usr/bin/mipns-xiaomi)" = a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d ]
    [ "$(hash /usr/lib/libxaudio_engine.so)" = 79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73 ]
    [ "$(hash /usr/bin/mico_aivs_lab)" = 7063b44fbe779c04c8bfc89e2870e1716eeb62765ba0025f8e8b68ea8026d18c ]
    [ "$(hash /usr/lib/libaivs_sdk.so)" = 21656da7ab6029e046e378270d7841629babc4d5b941ed27774bc25266678eda ]
    [ "$(hash /usr/lib/libaivs-message-util.so)" = c0fc1b551e20962e6dceeb4b1a24b3d8a454e19bec8fd692f2229241691a0c31 ]
    umask 077
    for name in pns mico_aivs_lab; do
        target=/etc/init.d/$name
        grep -q NATIVE_ASR_MANAGED_V1 "$target"
        ! grep -q "$TAG" "$target"
        cp "$target" "$D/$name.before"
        hash "$target" > "$D/$name.before.sha"
        awk -v tag="$TAG" -v dir="$D" '
            $0=="    procd_set_param env LD_PRELOAD=/data/native_asr.so" {
                print "    procd_set_param env LD_PRELOAD=" dir "/native_wake_probe.so # " tag; n++;next
            }
            {print}
            END {if(n!=1)exit 1}
        ' "$target" > "$D/$name.overlay"
        chmod 700 "$D/$name.overlay"
        sh -n "$D/$name.overlay"
        hash "$D/$name.overlay" > "$D/$name.overlay.sha"
    done
    token=$(cat /proc/sys/kernel/random/uuid)
    printf '%s\n' "$token" > "$D/timer.armed"
    now=$(awk '{print int($1)}' /proc/uptime)
    printf '%s\n' "$((now + restore_seconds))" > "$D/timer.deadline"
    trap restore 0
    (
        trap - 0
        trap '' HUP
        printf '%s\n' "$token" > "$D/timer.ready"
        sleep "$restore_seconds"
        [ "$(cat "$D/timer.armed" 2>/dev/null)" != "$token" ] || sh "$D/run_native_wake.sh" restore
    ) > "$D/timer.log" 2>&1 </dev/null &
    timer_pid=$!
    sleep 1
    [ "$(cat "$D/timer.ready")" = "$token" ]; kill -0 "$timer_pid"
    for name in pns mico_aivs_lab; do mount --bind "$D/$name.overlay" "/etc/init.d/$name"; done
    /etc/init.d/mico_aivs_lab restart
    /etc/init.d/pns restart
    sleep 4
    /data/native_asr_ctl status
    for process in mipns-xiaomi mico_aivs_lab; do
        pid=$(pidof "$process")
        case "$pid" in ''|*' '*) exit 1;; esac
        grep -q "$D/native_wake_probe.so" "/proc/$pid/maps"
    done
    pid=$(pidof mipns-xiaomi)
    tail -n 30 /tmp/native_followup/events.log | grep -q "pid=$pid FIRST_ENDPOINT callbacks end=0x184c0 worker=1"
    tail -n 30 /tmp/native_followup/events.log | grep -q "pid=$pid FIRST_ENDPOINT asr-callback supported=1"
    trap - 0
    echo WAKE_PROBE_INSTALLED
    ;;
*) exit 2;;
esac
