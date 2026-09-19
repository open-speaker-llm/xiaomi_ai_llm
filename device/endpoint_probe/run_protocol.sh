#!/bin/sh
# Explicit bounded replay experiment, separate from passive run.sh.
set -eu
D=/tmp/xiaomi_endpoint_protocol
TAG=XIAOMI_ENDPOINT_PROTOCOL
if [ "${XIAOMI_ENDPOINT_ACTIVE:-0}" = 1 ]; then
    D=/tmp/xiaomi_endpoint_active
    TAG=XIAOMI_ENDPOINT_ACTIVE
fi
hash() { sha256sum "$1" | awk '{print $1}'; }
# A spawned CLI is not proof that its native capture is ready. Wait for the
# exact sequence to bind, never announce readiness for a previous conversation.
wait_bound() {
    attempt=0
    while [ "$attempt" -lt 40 ]; do
        kill -0 "$listener" 2>/dev/null || return 1
        current=$(/data/native_asr_ctl status) || return 1
        if printf '%s\n' "$current" | grep -Eq "phase=4 sequence=$seq dialog=[^ ]+ final=0 "; then
            if [ "${vad:-0}" -ge 6 ] && ! grep -q "^NEURAL_STREAM sequence=$seq " "$out/neural.log"; then
                kill -0 "$neural_pid" 2>/dev/null || return 1
                attempt=$((attempt + 1));sleep 0.1;continue
            fi
            printf '%s\n' "$current" > "$out/ready.state"
            date > "$out/ready.time"
            echo "CAPTURE_READY case=$label sequence=$seq"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 0.1
    done
    return 1
}
restore() {
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
    rm -f "$D/armed" "$D/capture.armed" "$D/timer.armed"
    if [ "$changed" = 1 ]; then
        /etc/init.d/mico_aivs_lab restart
        /etc/init.d/pns restart
    fi
}
case "${1:-}" in
restore) restore; exit;;
setup)
    [ ! -e /tmp/native_first_busy ]
    sh /data/native_asr.sh status
    : "${EXPECTED_PROBE_SHA256:?}"
    [ "$(hash "$D/protocol_probe.so")" = "$EXPECTED_PROBE_SHA256" ]
    [ "$(hash /usr/bin/mipns-xiaomi)" = a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d ]
    [ "$(hash /usr/lib/libxaudio_engine.so)" = 79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73 ]
    [ "$(hash /usr/bin/mico_aivs_lab)" = 7063b44fbe779c04c8bfc89e2870e1716eeb62765ba0025f8e8b68ea8026d18c ]
    [ "$(hash /usr/lib/libaivs_sdk.so)" = 21656da7ab6029e046e378270d7841629babc4d5b941ed27774bc25266678eda ]
    [ ! -e "$D/timer.armed" ]
    umask 077
    for name in pns mico_aivs_lab; do
        target=/etc/init.d/$name
        grep -q NATIVE_ASR_MANAGED_V1 "$target"
        ! grep -q "$TAG" "$target"
        cp "$target" "$D/$name.before"
        hash "$target" > "$D/$name.before.sha"
        awk -v tag="$TAG" -v dir="$D" '
            $0=="    procd_set_param env LD_PRELOAD=/data/native_asr.so" {
                print "    procd_set_param env LD_PRELOAD=" dir "/protocol_probe.so # " tag; n++;next
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
    rm -f "$D/timer.ready"
    trap restore 0
    (
        trap - 0
        trap '' HUP
        printf '%s\n' "$token" > "$D/timer.ready"
        sleep 300
        [ "$(cat "$D/timer.armed" 2>/dev/null)" != "$token" ] || sh "$D/run_protocol.sh" restore
    ) > "$D/timer.log" 2>&1 </dev/null &
    timer_pid=$!
    sleep 1
    [ "$(cat "$D/timer.ready")" = "$token" ]
    kill -0 "$timer_pid"
    for name in pns mico_aivs_lab; do mount --bind "$D/$name.overlay" "/etc/init.d/$name"; done
    /etc/init.d/mico_aivs_lab restart
    /etc/init.d/pns restart
    sleep 4
    /data/native_asr_ctl status
    for process in mipns-xiaomi mico_aivs_lab; do
        pid=$(pidof "$process")
        case "$pid" in ''|*' '*) exit 1;; esac
        grep -q "$D/protocol_probe.so" "/proc/$pid/maps"
    done
    pid=$(pidof mipns-xiaomi)
    tail -n 20 /tmp/native_followup/events.log | grep -q "pid=$pid PROBE callbacks end=0x184c0 supported=1"
    tail -n 20 /tmp/native_followup/events.log | grep -q "pid=$pid PROBE end-worker rc=0"
    tail -n 20 /tmp/native_followup/events.log | grep -q "pid=$pid PROBE asr-callback supported=1"
    if [ "${XIAOMI_ENDPOINT_ACTIVE:-0}" = 1 ]; then
        tail -n 30 /tmp/native_followup/events.log | grep -q "pid=$pid ACTIVE vad-ready=1"
    fi
    trap - 0
    echo PROTOCOL_READY
    ;;
trial)
    kind=${2:-};vad=${3:-}
    label=${4:-unlabelled}
    case "$label:$kind:$vad:${XIAOMI_ENDPOINT_ACTIVE:-0}" in
        unlabelled:*) ;;
        A:microphone:5:1|B:microphone:5:1) ;;
        *) exit 2;;
    esac
    [ "$#" -le 4 ] || exit 2
    case "$kind:$vad:${XIAOMI_ENDPOINT_ACTIVE:-0}" in
        short:[0-3]:0|long:[0-3]:0) ;;
        neural-end:7:1|neural:6:1|capture:5:1|tail:3:1|delay:3:1|short:4:1|long:4:1|live:4:1|normal:4:1|soft:4:1|noise:4:1|silence:4:1|microphone:5:1) ;;
        *) exit 2;;
    esac
    [ ! -e /tmp/native_first_busy ]
    for name in pns mico_aivs_lab; do grep -q "$TAG" "/etc/init.d/$name"; done
    status=$(/data/native_asr_ctl status)
    echo "$status" | grep -Eq 'phase=(0|7|8) '
    seq=$(printf '%s\n' "$status" | sed -n 's/.*sequence=\([0-9]*\).*/\1/p')
    seq=$((seq + 1))
    out=$(mktemp -d "$D/trial.$kind.$vad.XXXXXX")
    umask 077
    printf '%s\n' "$status" > "$out/before.state"
    printf '%s\n' "$label" > "$out/case"
    if [ "$vad" -lt 5 ]; then
        cp "$D/$kind.pcm" "$D/input.pcm"
        chmod 600 "$D/input.pcm"
    fi
    printf '%s %s %s\n' "$seq" "$$" "$vad" > "$D/armed"
    rm -f "$D/capture.armed"
    if [ "$kind" = capture ]; then
        cp "$D/armed" "$D/capture.armed"
        printf '%s\n' 'Exact ASR callback; mono 16000 Hz S16LE; at most 20 s; diagnosis only.' > "$out/audio-format.txt"
    fi
    date +%s > /tmp/native_first_busy
    tail -n 0 -f /tmp/log/messages > "$out/system.log" & sys=$!
    tail -n 0 -f /tmp/native_followup/events.log > "$out/probe.log" & events=$!
    cleanup_trial() {
        if [ "${listener_running:-0}" = 1 ]; then
            kill "$listener" 2>/dev/null || true
            wait "$listener" 2>/dev/null || true
        fi
        rm -f "$D/armed" "$D/capture.armed"
        if [ -n "${neural_pid:-}" ]; then
            kill "$neural_pid" 2>/dev/null || true
            wait "$neural_pid" 2>/dev/null || true
        fi
        # A real wake may remove/replace busy. Never erase another owner's flag.
        if [ -f /tmp/native_first_busy ] && [ "$(cat /tmp/native_first_busy)" = "$busy" ]; then rm -f /tmp/native_first_busy; fi
        kill "$sys" "$events" 2>/dev/null || true
    }
    busy=$(cat /tmp/native_first_busy)
    trap cleanup_trial 0
    neural_pid=
    if [ "$vad" -ge 6 ]; then
        : "${EXPECTED_NEURAL_MANIFEST_SHA256:?}"
        stream="$D/shadow.$seq.$$.stream"
        set -- "$stream" "$seq" "$$"
        [ "$vad" != 7 ] || set -- "$@" endpoint
        sh "$D/run_neural_shadow.sh" "$@" > "$out/neural.log" 2>&1 &
        neural_pid=$!
        attempts=0
        until grep -q "^NEURAL_READY sequence=$seq owner=$$ " "$out/neural.log"; do
            kill -0 "$neural_pid" 2>/dev/null || { cat "$out/neural.log"; exit 1; }
            attempts=$((attempts + 1));[ "$attempts" -le 60 ] || exit 1
            sleep 0.1
        done
    fi
    echo "PROTOCOL_TRIAL $out seq=$seq cloud_vad=$vad"
    date > "$out/start"
    rc=0
    lease_seconds=25
    [ "$vad" -lt 6 ] || lease_seconds=30
    /data/native_asr_ctl listen "$$" "$lease_seconds" > "$out/text" & listener=$!
    listener_running=1
    if ! wait_bound; then
        echo "CAPTURE_NOT_READY case=$label sequence=$seq" >&2
        kill "$listener" 2>/dev/null || true
    fi
    wait "$listener" || rc=$?
    listener_running=0
    if [ "$vad" -ge 6 ]; then
        neural_rc=0
        wait "$neural_pid" || neural_rc=$?
        neural_pid=
        printf '%s\n' "$neural_rc" > "$out/neural.rc"
        [ "$neural_rc" = 0 ] || rc=1
        [ ! -f "$stream" ] || mv "$stream" "$out/input.stream"
        [ ! -f "$stream.decision" ] || mv "$stream.decision" "$out/decision.bin"
    fi
    printf '%s\n' "$rc" > "$out/rc"
    sleep 2
    if [ "$kind" = capture ] && [ -f "$D/capture.$seq.$$.pcm" ]; then
        mv "$D/capture.$seq.$$.pcm" "$out/input.pcm"
    fi
    cp /tmp/mico_aivs_lab/event.log "$out/events.jsonl"
    cp /tmp/mico_aivs_lab/instruction.log "$out/instructions.jsonl"
    /data/native_asr_ctl status > "$out/state"
    echo "PROTOCOL_DONE rc=$rc"
    cat "$out/text"
    ;;
*) echo 'setup | trial short|long 0|1|2|3 | restore'; exit 2;;
esac
