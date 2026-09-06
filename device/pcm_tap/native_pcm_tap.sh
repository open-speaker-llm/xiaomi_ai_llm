#!/bin/sh
# Reversible boot1-only procd overlay. Never writes the firmware partition.
set -u
PNS=/etc/init.d/pns
OVERLAY=/tmp/native_pcm_tap.managed.pns
TAP=/data/xaudio_pcm_tap.so
CAPTURE=/data/capture_pcm
RING=/tmp/native_followup_pcm.ring
TAG=NATIVE_PCM_TAP_MANAGED_V1

log() { echo "[PCM-TAP] $*"; }
is_boot1() { [ "$(awk '$2 == "/" {print $1; exit}' /proc/mounts)" = /dev/mtdblock5 ]; }
mounted() { awk '$2 == "/etc/init.d/pns" {found=1} END {exit !found}' /proc/mounts; }
owned() { mounted && grep -q "$TAG" "$PNS"; }
hash_is() { [ "$(sha256sum "$1" 2>/dev/null | awk '{print $1}')" = "$2" ]; }
verified_audio() {
    hash_is /usr/bin/mipns-xiaomi a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d &&
    hash_is /usr/lib/libxaudio_engine.so 79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73
}
healthy() {
    local pid
    for pid in $(pidof mipns-xiaomi 2>/dev/null); do
        grep -q "$TAP" "/proc/$pid/maps" 2>/dev/null || continue
        "$CAPTURE" --check >/dev/null 2>&1 && return 0
    done
    return 1
}
stop_tap() {
    if owned; then
        umount "$PNS" || return 1
        "$PNS" restart || return 1
        rm -f "$OVERLAY" "$RING"
        log "restored native procd service"
    elif mounted; then
        log "foreign PNS overlay; left untouched"
        return 1
    fi
}
start_tap() {
    is_boot1 || { log "boot0: skip"; return 0; }
    verified_audio || { log "firmware ABI hash mismatch; refuse injection"; return 1; }
    [ -r "$TAP" ] && [ -x "$CAPTURE" ] || { log "binaries missing"; return 1; }
    if owned; then
        healthy && { log "already healthy"; return 0; }
        stop_tap || return 1
    elif mounted; then
        log "foreign PNS overlay; refuse replacement"
        return 1
    fi
    hash_is "$PNS" d9544da4c47bebce556eb656ff5679a6eb90b49255d51f5f740c74706e25a1d7 || {
        log "PNS script hash mismatch; refuse injection"; return 1;
    }
    umask 077
    awk -v tag="$TAG" -v tap="$TAP" '
        {print}
        /^_start_mipns_xiaomi\(\)/ {xiaomi=1}
        xiaomi && /^[[:space:]]*procd_open_instance[[:space:]]*$/ {
            print "    # " tag
            print "    procd_set_param env LD_PRELOAD=" tap
            xiaomi=0; count++
        }
        END {if(count!=1) exit 1}
    ' "$PNS" > "$OVERLAY" || return 1
    sh -n "$OVERLAY" || return 1
    chmod 700 "$OVERLAY"
    mount --bind "$OVERLAY" "$PNS" || return 1
    # Every startup failure below restores the original service.
    if "$PNS" restart; then
        local attempt=0
        while [ "$attempt" -lt 5 ]; do
            sleep 1
            if healthy; then
                log "ready: processed PCM 16k mono; native capture retained"
                return 0
            fi
            attempt=$((attempt + 1))
        done
    fi
    log "startup health failed; restoring native service"
    stop_tap
    return 1
}

case "${1:-status}" in
    start) start_tap ;;
    stop) is_boot1 && stop_tap ;;
    status) owned && healthy && { log "healthy"; exit 0; }; log "inactive or unhealthy"; exit 1 ;;
    *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
