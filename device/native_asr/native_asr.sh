#!/bin/sh
# Persistent, reversible overlays for one verified boot1 firmware.
set -u
DIR=/tmp/native_followup
SO=/data/native_asr.so
CTL=/data/native_asr_ctl
PNS=/etc/init.d/pns
AIVS=/etc/init.d/mico_aivs_lab
TAG=NATIVE_ASR_MANAGED_V1
log() { echo "[NATIVE-ASR] $*"; }
is_boot1() { [ "$(awk '$2 == "/" {print $1;exit}' /proc/mounts)" = /dev/mtdblock5 ]; }
mounted() { awk -v p="$1" '$2==p {found=1} END {exit !found}' /proc/mounts; }
owned() { mounted "$1" && grep -q "$TAG" "$1"; }
hash_is() { [ "$(sha256sum "$1" 2>/dev/null | awk '{print $1}')" = "$2" ]; }
verified() {
    hash_is /usr/bin/mipns-xiaomi a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d &&
    hash_is /usr/lib/libxaudio_engine.so 79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73 &&
    hash_is /usr/bin/mico_aivs_lab 7063b44fbe779c04c8bfc89e2870e1716eeb62765ba0025f8e8b68ea8026d18c &&
    hash_is /usr/lib/libaivs-message-util.so c0fc1b551e20962e6dceeb4b1a24b3d8a454e19bec8fd692f2229241691a0c31 &&
    hash_is /usr/lib/libaivs_sdk.so 21656da7ab6029e046e378270d7841629babc4d5b941ed27774bc25266678eda
}
healthy() {
    local pid
    owned "$PNS" && owned "$AIVS" || return 1
    for process in mipns-xiaomi mico_aivs_lab; do
        pid=$(pidof "$process" 2>/dev/null)
        case "$pid" in ''|*' '*) return 1;; esac
        grep -q "$SO" "/proc/$pid/maps" || return 1
    done
    "$CTL" status >/dev/null 2>&1
}
stop_native_asr() {
    local changed=0 p
    for p in "$PNS" "$AIVS"; do
        if mounted "$p" && ! owned "$p"; then log "foreign overlay: $p; left untouched"; return 1; fi
    done
    for p in "$PNS" "$AIVS"; do
        if owned "$p"; then umount "$p" || return 1; changed=1; fi
    done
    if [ "$changed" = 1 ]; then
        "$AIVS" restart
        "$PNS" restart
        log "original native services restored"
    fi
}
start_native_asr() {
    is_boot1 || { log "boot0: skip"; return 0; }
    verified || { log "firmware ABI hash mismatch; refuse injection"; return 1; }
    [ -r "$SO" ] && [ -x "$CTL" ] || { log "binaries missing"; return 1; }
    healthy && { log "already healthy"; return 0; }
    for p in "$PNS" "$AIVS"; do
        if mounted "$p" && ! owned "$p"; then log "foreign overlay: $p; refuse replacement"; return 1; fi
    done
    stop_native_asr || return 1
    hash_is "$PNS" d9544da4c47bebce556eb656ff5679a6eb90b49255d51f5f740c74706e25a1d7 &&
    hash_is "$AIVS" cc17eb3e7b4981098aa145c88804be57dbd931fb0cf7dd9ea19fafd7a432c819 || {
        log "init script hash mismatch"; return 1;
    }
    umask 077
    mkdir -p "$DIR"
    rm -f "$DIR/state"
    "$CTL" init || return 1
    awk -v tag="$TAG" -v so="$SO" '
        {print}
        /^_start_mipns_xiaomi\(\)/ {xiaomi=1}
        xiaomi && /^[[:space:]]*procd_open_instance[[:space:]]*$/ {
            print "    # " tag; print "    procd_set_param env LD_PRELOAD=" so
            xiaomi=0; count++
        }
        END {if(count!=1) exit 1}
    ' "$PNS" > "$DIR/pns" || return 1
    awk -v tag="$TAG" -v so="$SO" '
        {print}
        /^[[:space:]]*procd_open_instance[[:space:]]*$/ {
            print "    # " tag; print "    procd_set_param env LD_PRELOAD=" so; count++
        }
        END {if(count!=1) exit 1}
    ' "$AIVS" > "$DIR/aivs" || return 1
    sh -n "$DIR/pns" && sh -n "$DIR/aivs" || return 1
    chmod 700 "$DIR/pns" "$DIR/aivs"
    mount --bind "$DIR/aivs" "$AIVS" || return 1
    if mount --bind "$DIR/pns" "$PNS" && "$AIVS" restart && "$PNS" restart; then
        local attempt=0
        while [ "$attempt" -lt 15 ]; do
            sleep 1
            healthy && { log "ready: native ASR-only followup"; return 0; }
            attempt=$((attempt+1))
        done
    fi
    log "startup failed; restoring original services"
    stop_native_asr
    return 1
}
case "${1:-status}" in
    start) start_native_asr;;
    stop) is_boot1 && stop_native_asr;;
    status) healthy && { log healthy; "$CTL" status; exit 0; }; log inactive; exit 1;;
    *) echo "usage: $0 start|stop|status" >&2; exit 2;;
esac
