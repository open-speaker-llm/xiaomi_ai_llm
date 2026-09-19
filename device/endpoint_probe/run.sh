#!/bin/sh
# Bounded observation only. No ASR request rewrite, synthetic audio, or LLM call.
# Requires the existing, verified native ASR deployment to be idle.
set -eu
D=/tmp/xiaomi_endpoint_probe
PNS=/etc/init.d/pns
TAG=XIAOMI_ENDPOINT_OBSERVER
hash() { sha256sum "$1" | awk '{print $1}'; }
start_rollback_timer() {
    token=$1
    rm -f "$D/rollback.ready"
    # This BusyBox image has no nohup. Ignore HUP before acknowledging readiness.
    (
        trap '' HUP
        printf '%s\n' "$token" > "$D/rollback.ready"
        sleep 300
        [ "$(cat "$D/rollback.armed" 2>/dev/null)" != "$token" ] || sh "$D/run.sh" restore
    ) > "$D/rollback.log" 2>&1 </dev/null &
    timer_pid=$!
    attempts=0
    until [ "$(cat "$D/rollback.ready" 2>/dev/null)" = "$token" ]; do
        kill -0 "$timer_pid" 2>/dev/null || return 1
        attempts=$((attempts + 1))
        [ "$attempts" -le 5 ] || return 1
        sleep 1
    done
    kill -0 "$timer_pid"
}
case "${1:-}" in
    restore)
        [ -d "$D" ] || exit 0
        # Only remove our exact top overlay. Never pop an unrelated mount.
        if grep -q "$TAG" "$PNS"; then
            [ "$(hash "$PNS")" = "$(cat "$D/overlay.sha256")" ] || exit 1
            umount "$PNS"
            [ "$(hash "$PNS")" = "$(cat "$D/before.sha256")" ] || exit 1
            "$PNS" restart
        fi
        rm -f "$D/rollback.armed"
        exit 0
        ;;
    capture|shadow)
        mode=$1
        seconds=${2:-20}
        case "$seconds" in ''|*[!0-9]*) exit 2;; esac
        [ "$seconds" -ge 5 ] && [ "$seconds" -le 30 ]
        grep -q "$TAG" "$PNS"
        sh /data/native_asr.sh status >/dev/null
        recorder="$D/capture_pcm"
        if [ "$mode" = shadow ]; then
            : "${EXPECTED_SHADOW_SHA256:?}"
            recorder="$D/shadow_capture"
            [ "$(hash "$recorder")" = "$EXPECTED_SHADOW_SHA256" ]
        fi
        # New directory for every attempt; never overwrite an earlier trial.
        out=$(mktemp -d "$D/trial.XXXXXX")
        chmod 700 "$out"
        date '+%Y-%m-%dT%H:%M:%S%z' > "$out/start.wall"
        cat /proc/uptime > "$out/start.uptime"
        tail -n 0 -f /tmp/log/messages > "$out/system.log" &
        sys_pid=$!
        tail -n 0 -f /tmp/native_first_client.log > "$out/client.log" &
        cli_pid=$!
        capture_pid=
        trap 'kill "$sys_pid" "$cli_pid" ${capture_pid:+"$capture_pid"} 2>/dev/null || true' 0
        rc=0
        PCM_CAPTURE_TIMELINE=1 "$recorder" "$out/audio.wav" "$seconds" > "$out/capture.log" 2>&1 &
        capture_pid=$!
        attempts=0
        until grep -q '^PCM_CLOCK ' "$out/capture.log"; do
            kill -0 "$capture_pid" 2>/dev/null || { cat "$out/capture.log"; exit 1; }
            attempts=$((attempts + 1))
            [ "$attempts" -le 3 ] || exit 1
            sleep 1
        done
        echo "CAPTURE_READY $out seconds=$seconds mode=$mode"
        wait "$capture_pid" || rc=$?
        capture_pid=
        cat /proc/uptime > "$out/end.uptime"
        date '+%Y-%m-%dT%H:%M:%S%z' > "$out/end.wall"
        cp /tmp/mico_aivs_lab/event.log "$out/events.jsonl"
        cp /tmp/mico_aivs_lab/instruction.log "$out/instructions.jsonl"
        cp /tmp/native_followup/events.log "$out/followup.log"
        echo "CAPTURE_DONE $out rc=$rc"
        exit "$rc"
        ;;
    setup) ;;
    *) echo 'usage: run.sh setup | capture|shadow [5..30 seconds] | restore' >&2; exit 2;;
esac

[ "$(awk '$2=="/" {print $1;exit}' /proc/mounts)" = /dev/mtdblock5 ]
[ ! -e /tmp/native_first_busy ]
sh /data/native_asr.sh status >/dev/null
[ "$(hash /usr/bin/mipns-xiaomi)" = a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d ]
[ "$(hash /usr/lib/libxaudio_engine.so)" = 79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73 ]
# Values supplied from freshly built/verified tools, never accepted from the device itself.
: "${EXPECTED_TAP_SHA256:?}" "${EXPECTED_CAPTURE_SHA256:?}"
[ "$(hash "$D/xaudio_pcm_tap.so")" = "$EXPECTED_TAP_SHA256" ]
[ "$(hash "$D/capture_pcm")" = "$EXPECTED_CAPTURE_SHA256" ]
grep -q NATIVE_ASR_MANAGED_V1 "$PNS"
! grep -q "$TAG" "$PNS"
pid=$(pidof mipns-xiaomi)
case "$pid" in ''|*' '*) exit 1;; esac
! grep -q xaudio_pcm_tap.so "/proc/$pid/maps"
umask 077
mkdir -p "$D"
# Refuse an unfinished older observation rather than overwriting its recovery point.
[ ! -e "$D/rollback.armed" ]
cp "$PNS" "$D/pns.before"
hash "$D/pns.before" > "$D/before.sha256"
awk -v tag="$TAG" '
    $0 == "    procd_set_param env LD_PRELOAD=/data/native_asr.so" {
        print "    procd_set_param env \"LD_PRELOAD=/tmp/xiaomi_endpoint_probe/xaudio_pcm_tap.so /data/native_asr.so\" # " tag
        n++; next
    }
    {print}
    END {if(n!=1) exit 1}
' "$D/pns.before" > "$D/pns.observer"
sh -n "$D/pns.observer"
chmod 700 "$D/pns.observer"
hash "$D/pns.observer" > "$D/overlay.sha256"
[ -r "$D/run.sh" ]
token="$(cat /proc/sys/kernel/random/uuid)"
printf '%s\n' "$token" > "$D/rollback.armed"
trap 'sh "$D/run.sh" restore' 0
# Fail before mounting if the detached timer does not acknowledge startup.
start_rollback_timer "$token"
mount --bind "$D/pns.observer" "$PNS"
"$PNS" restart
sleep 4
sh /data/native_asr.sh status >/dev/null
"$D/capture_pcm" --check
trap - 0
echo 'OBSERVER_READY auto_restore=300s'
