#!/bin/sh
#
# Probe Xiaomi native audio/ASR surfaces without changing the main client.
# Default mode is read-only inventory. Use record mode explicitly to sample PCM.
#

OUT_DIR="${OUT_DIR:-/tmp/native_audio_probe}"
SECONDS="${SECONDS:-3}"

log() {
    echo "[$(date '+%H:%M:%S.%N' 2>/dev/null | cut -c1-12)] $*"
}

run() {
    local title="$1"
    shift
    {
        echo
        echo "===== $title ====="
        "$@" 2>&1
    } >> "$OUT_DIR/inventory.log"
}

safe_strings() {
    local file="$1"
    local name

    [ -f "$file" ] || return 0
    name=$(basename "$file")
    {
        echo
        echo "===== strings $file ====="
        strings "$file" 2>/dev/null \
            | grep -Ei 'asr|vad|aec|beam|mvdr|pcm|alsa|capture|record|recorder|mic|audio|opus|wav|fifo|sock|usock|mibrain|aivs|recognize|speech|multirounds|continuous|follow|tts|pns|wakeup' \
            | sort -u
    } > "$OUT_DIR/strings_$name.log"
}

inventory() {
    rm -rf "$OUT_DIR"
    mkdir -p "$OUT_DIR"
    : > "$OUT_DIR/inventory.log"

    log "inventory start: $OUT_DIR" | tee -a "$OUT_DIR/inventory.log"
    run "date" date
    run "root mount" sh -c "mount | head -40"
    run "key processes" sh -c "ps | grep -E 'mipns|mico_aivs|mibrain|pns_ubus|mediaplayer|xaudio|native_first|arecord|aplay' | grep -v grep"
    run "asound conf" sh -c "cat /etc/asound.conf 2>/dev/null; echo; cat /usr/share/alsa/alsa.conf 2>/dev/null | head -80"
    run "proc asound" sh -c "cat /proc/asound/cards 2>/dev/null; echo; cat /proc/asound/devices 2>/dev/null; echo; cat /proc/asound/pcm 2>/dev/null"
    run "alsa devices" sh -c "arecord -l 2>/dev/null; echo ---; arecord -L 2>/dev/null; echo ---; aplay -l 2>/dev/null; echo ---; aplay -L 2>/dev/null"
    run "dev snd" sh -c "ls -l /dev/snd 2>/dev/null"
    run "ubus list" sh -c "ubus -v list mibrain 2>/dev/null; echo ---; ubus -v list pnshelper 2>/dev/null; echo ---; ubus -v list 2>/dev/null | grep -Ei 'brain|aivs|asr|speech|audio|pns|media|player|voice'"
    run "tmp sockets fifos" sh -c "find /tmp -maxdepth 3 \\( -type s -o -type p \\) -ls 2>/dev/null | sort"
    run "recent tmp audio-ish" sh -c "find /tmp /data -maxdepth 4 -type f \\( -name '*.wav' -o -name '*.pcm' -o -name '*.opus' -o -name '*.mp3' -o -name '*asr*' -o -name '*voice*' -o -name '*audio*' \\) -ls 2>/dev/null | sort -k 8,9 | tail -120"
    run "process fd audio ipc" sh -c '
for p in $(pidof mipns-xiaomi mico_aivs_lab mibrain_service pns_ubus_helper mediaplayer 2>/dev/null); do
    echo "--- pid=$p $(cat /proc/$p/cmdline 2>/dev/null | tr "\0" " ") ---"
    ls -l /proc/$p/fd 2>/dev/null | grep -Ei "snd|pcm|audio|voice|asr|aivs|mibrain|mipns|fifo|socket|usock|tmp" || true
done'
    run "process maps xiaomi libs" sh -c '
for p in $(pidof mipns-xiaomi mico_aivs_lab mibrain_service pns_ubus_helper 2>/dev/null); do
    echo "--- pid=$p maps ---"
    grep -Ei "xaudio|asr|vad|aec|opus|alsa|mibrain|aivs|speech" /proc/$p/maps 2>/dev/null | sort -u
done'

    for f in \
        /usr/bin/mipns-xiaomi \
        /usr/bin/mico_aivs_lab \
        /usr/bin/mibrain_service \
        /usr/bin/pns_ubus_helper \
        /usr/bin/mediaplayer \
        /usr/share/xiaomi/xaudio_engine.conf \
        /usr/share/xiaomi/mibrain/mibrain.conf \
        /bin/wakeup.sh \
        /tmp/wakeup.sh.orig
    do
        safe_strings "$f"
    done

    log "inventory done: $OUT_DIR"
    ls -lh "$OUT_DIR"
}

record_one() {
    local name="$1"
    local dev="$2"
    local fmt="$3"
    local rate="$4"
    local ch="$5"
    local out="$OUT_DIR/${name}.wav"

    log "record $name dev=$dev fmt=$fmt rate=$rate ch=$ch ${SECONDS}s"
    arecord -D "$dev" -f "$fmt" -r "$rate" -c "$ch" -d "$SECONDS" "$out" > "$OUT_DIR/${name}.log" 2>&1
    echo "$name ret=$? bytes=$(wc -c < "$out" 2>/dev/null) file=$out" | tee -a "$OUT_DIR/record.log"
}

record() {
    mkdir -p "$OUT_DIR"
    : > "$OUT_DIR/record.log"

    record_one capture_8ch_s32_48k Capture S32_LE 48000 8
    record_one hw02_8ch_s32_48k hw:0,2 S32_LE 48000 8
    record_one default_1ch_s16_16k default S16_LE 16000 1
    record_one capture_1ch_s16_16k Capture S16_LE 16000 1

    log "record done: $OUT_DIR"
    ls -lh "$OUT_DIR"
}

case "$1" in
    inventory|"")
        inventory
        ;;
    record)
        record
        ;;
    *)
        echo "Usage: $0 {inventory|record}"
        echo "Env: OUT_DIR=/tmp/native_audio_probe SECONDS=3"
        exit 1
        ;;
esac
