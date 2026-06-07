#!/bin/sh
#
# 小米AI音箱 LLM 对话助手 — Native-first 版
#
# 原生小爱优先：唤醒、ASR、NLP、家电控制、普通小米问答都先走小米原生链路。
# 小米返回白名单 domain 时使用小米；非白名单 domain 立即 fallback 到 Mac LLM。
#

CONFIG_FILE="${CONFIG_FILE:-/data/native_first.env}"
[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"

SERVER="${SERVER:-http://192.168.8.150:8080}"
BACKEND="${BACKEND:-deepseek}"
VAD_SCRIPT="${VAD_SCRIPT:-/data/vad_record.sh}"
LLM_VOLUME="${LLM_VOLUME:-1.2}"
LLM_MASTER_VOLUME="${LLM_MASTER_VOLUME:-auto}"
LLM_MASTER_SCALE="${LLM_MASTER_SCALE:-145}"
LLM_MASTER_CURRENT_SCALE="${LLM_MASTER_CURRENT_SCALE:-112}"
LLM_MASTER_MIN="${LLM_MASTER_MIN:-96}"
LLM_MASTER_MAX="${LLM_MASTER_MAX:-196}"
EVENT_FIFO="/tmp/native_first_event.fifo"
EVENT_LOG="/tmp/native_first_events.log"
PLAYER_FROZEN_MARKER="/tmp/native_first_player_frozen"
BUSY_MARKER="/tmp/native_first_busy"
LAST_LLM_QUERY_FILE="/tmp/native_first_last_llm_query"
LAST_LLM_TS_FILE="/tmp/native_first_last_llm_ts"
LOG_FILE="${LOG_FILE:-/tmp/native_first_client.log}"
PID_FILE="${PID_FILE:-/tmp/native_first_client.pid}"
ORIG_WAKEUP="/tmp/wakeup.sh.orig"
HOOK_WAKEUP="/tmp/wakeup.sh.native_first_client"
MIPNS_CONF="${MIPNS_CONF:-/usr/share/xiaomi/xaudio_engine.conf}"
MIPNS_ARGS="${MIPNS_ARGS:--r opus32 -l}"
AUDIO_CAPTURE_SETUP="${AUDIO_CAPTURE_SETUP:-auto}"
NATIVE_RESULT_SOURCE="${NATIVE_RESULT_SOURCE:-auto}"
NATIVE_AIVS_LAB_RESULT_SYSTEM1="${NATIVE_AIVS_LAB_RESULT_SYSTEM1:-1}"
SYSTEM1_NATIVE_WAIT_SECONDS="${SYSTEM1_NATIVE_WAIT_SECONDS:-3}"
SYSTEM1_FOLLOWUP_ENABLED="${SYSTEM1_FOLLOWUP_ENABLED:-0}"
SYSTEM1_FOLLOWUP_CAPTURE_MIPNS="${SYSTEM1_FOLLOWUP_CAPTURE_MIPNS:-0}"
SYSTEM1_FOLLOWUP_ASR_ENGINE="${SYSTEM1_FOLLOWUP_ASR_ENGINE:-mac}"
SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_DEV="${SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_DEV:-hw:0,2}"
SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_FORMAT="${SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_FORMAT:-S32_LE}"
SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_RATE="${SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_RATE:-48000}"
SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_CHANNELS="${SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_CHANNELS:-8}"
AIVS_LAB_INSTRUCTION_LOG="${AIVS_LAB_INSTRUCTION_LOG:-/tmp/mico_aivs_lab/instruction.log}"
AIVS_LAB_LOOKBACK_LINES="${AIVS_LAB_LOOKBACK_LINES:-40}"
AIVS_LAB_LAST_DIALOG_FILE="${AIVS_LAB_LAST_DIALOG_FILE:-/tmp/native_first_last_aivs_dialog}"
NATIVE_WAIT_SECONDS="${NATIVE_WAIT_SECONDS:-12}"
NATIVE_POLL_INTERVAL="${NATIVE_POLL_INTERVAL:-0.2}"
NATIVE_UBUS_TIMEOUT="${NATIVE_UBUS_TIMEOUT:-1}"
WAKE_EVENT_MAX_AGE="${WAKE_EVENT_MAX_AGE:-4}"
WAKE_IGNORE_QUERIES="${WAKE_IGNORE_QUERIES:-${WAKE_ONLY_QUERIES:-小爱同学 小爱 小爱小爱 小爱同学小爱同学 我在 在呢}}"
FOLLOWUP_TIMEOUT="${FOLLOWUP_TIMEOUT:-8}"
FOLLOWUP_ENABLED="${FOLLOWUP_ENABLED:-1}"
FOLLOWUP_MODE="${FOLLOWUP_MODE:-local_record}"
FOLLOWUP_THRESHOLD="${FOLLOWUP_THRESHOLD:-180}"
FOLLOWUP_START_HITS="${FOLLOWUP_START_HITS:-1}"
FOLLOWUP_END_THRESHOLD="${FOLLOWUP_END_THRESHOLD:-100}"
FOLLOWUP_START_RMS_THRESHOLD="${FOLLOWUP_START_RMS_THRESHOLD:-115}"
FOLLOWUP_END_RMS_THRESHOLD="${FOLLOWUP_END_RMS_THRESHOLD:-60}"
FOLLOWUP_START_ACTIVE_PERMILLE="${FOLLOWUP_START_ACTIVE_PERMILLE:-80}"
FOLLOWUP_END_ACTIVE_PERMILLE="${FOLLOWUP_END_ACTIVE_PERMILLE:-20}"
FOLLOWUP_IGNORE_INITIAL_CHUNKS="${FOLLOWUP_IGNORE_INITIAL_CHUNKS:-2}"
FOLLOWUP_TAIL_RMS_THRESHOLD="${FOLLOWUP_TAIL_RMS_THRESHOLD:-70}"
FOLLOWUP_TAIL_ACTIVE_PERMILLE="${FOLLOWUP_TAIL_ACTIVE_PERMILLE:-30}"
FOLLOWUP_SILENCE_LIMIT="${FOLLOWUP_SILENCE_LIMIT:-3}"
FOLLOWUP_PREARM="${FOLLOWUP_PREARM:-1}"
FOLLOWUP_PREARM_EXTRA="${FOLLOWUP_PREARM_EXTRA:-3}"
FOLLOWUP_ARM_DELAY="${FOLLOWUP_ARM_DELAY:-0.2}"
FOLLOWUP_MIN_RAW_BYTES="${FOLLOWUP_MIN_RAW_BYTES:-16000}"
FOLLOWUP_ASR_ENGINE="${FOLLOWUP_ASR_ENGINE:-native}"
FOLLOWUP_NATIVE_ASR_TIMEOUT="${FOLLOWUP_NATIVE_ASR_TIMEOUT:-30}"
FOLLOWUP_NATIVE_ASR_FALLBACK_MAC="${FOLLOWUP_NATIVE_ASR_FALLBACK_MAC:-0}"
FOLLOWUP_NATIVE_MIN_QUERY_BYTES="${FOLLOWUP_NATIVE_MIN_QUERY_BYTES:-10}"
FOLLOWUP_RECORD_MODE="${FOLLOWUP_RECORD_MODE:-window}"
FOLLOWUP_WINDOW_SECONDS="${FOLLOWUP_WINDOW_SECONDS:-5}"
FOLLOWUP_WINDOW_CAPTURE_DEV="${FOLLOWUP_WINDOW_CAPTURE_DEV:-Capture}"
FOLLOWUP_WINDOW_MIN_PEAK="${FOLLOWUP_WINDOW_MIN_PEAK:-300}"
FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD="${FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD:-40}"
FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE="${FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE:-5}"
if [ "$FOLLOWUP_ASR_ENGINE" = "native" ]; then
    FOLLOWUP_WINDOW_CAPTURE_FORMAT="${FOLLOWUP_WINDOW_CAPTURE_FORMAT:-S16_LE}"
    FOLLOWUP_WINDOW_CAPTURE_RATE="${FOLLOWUP_WINDOW_CAPTURE_RATE:-16000}"
    FOLLOWUP_WINDOW_CAPTURE_CHANNELS="${FOLLOWUP_WINDOW_CAPTURE_CHANNELS:-1}"
else
    FOLLOWUP_WINDOW_CAPTURE_FORMAT="${FOLLOWUP_WINDOW_CAPTURE_FORMAT:-S32_LE}"
    FOLLOWUP_WINDOW_CAPTURE_RATE="${FOLLOWUP_WINDOW_CAPTURE_RATE:-48000}"
    FOLLOWUP_WINDOW_CAPTURE_CHANNELS="${FOLLOWUP_WINDOW_CAPTURE_CHANNELS:-8}"
fi
FOLLOWUP_ARM_FILE="/tmp/native_followup_vad.arm"
NATIVE_FOLLOWUP_POLL_SECONDS="${NATIVE_FOLLOWUP_POLL_SECONDS:-12}"
NATIVE_FOLLOWUP_POLL_INTERVAL="${NATIVE_FOLLOWUP_POLL_INTERVAL:-0.2}"
NATIVE_FOLLOWUP_PRE_MULTIROUNDS="${NATIVE_FOLLOWUP_PRE_MULTIROUNDS:-1}"
NATIVE_FOLLOWUP_TTS_NOTIFY="${NATIVE_FOLLOWUP_TTS_NOTIFY:-1}"
NATIVE_FOLLOWUP_MULTIROUNDS_TRIGGER="${NATIVE_FOLLOWUP_MULTIROUNDS_TRIGGER:-pns}"
NATIVE_FOLLOWUP_TRIGGER_AFTER_TTS_END="${NATIVE_FOLLOWUP_TRIGGER_AFTER_TTS_END:-0}"
STREAM_TIMEOUT="${STREAM_TIMEOUT:-180}"
UNSUPPORTED_PATTERNS="${UNSUPPORTED_PATTERNS:-暂时|不会|不支持|回答不上|需要再学习|没听懂|不知道|不会这项技能}"
DIRECT_LLM_QUERY_PATTERNS="${DIRECT_LLM_QUERY_PATTERNS:-DEEPSEEK|DeepSeek|deepseek}"
NATIVE_SUCCESS_DOMAINS="${NATIVE_SUCCESS_DOMAINS:-smartMiot soundboxControl time weather music player alarm timer system volume}"
NATIVE_REPLAY_SUCCESS_SPEAK="${NATIVE_REPLAY_SUCCESS_SPEAK:-1}"
NATIVE_REPLAY_SUCCESS_DELAY="${NATIVE_REPLAY_SUCCESS_DELAY:-0}"
NATIVE_REPLAY_CANCEL_ON_WAKE="${NATIVE_REPLAY_CANCEL_ON_WAKE:-1}"
NATIVE_REPLAY_CANCEL_DOMAINS="${NATIVE_REPLAY_CANCEL_DOMAINS:-smartMiot soundboxControl volume system}"
NATIVE_REPLAY_CANCEL_GRACE="${NATIVE_REPLAY_CANCEL_GRACE:-0.2}"
NATIVE_REPLAY_CANCEL_WINDOW="${NATIVE_REPLAY_CANCEL_WINDOW:-4}"
NATIVE_REPLAY_CANCEL_MARKER="${NATIVE_REPLAY_CANCEL_MARKER:-/tmp/native_first_replay_cancel}"
STOP_NATIVE_SECONDS="${STOP_NATIVE_SECONDS:-15}"
SUPPRESS_DUP_SECONDS="${SUPPRESS_DUP_SECONDS:-0}"
FREEZE_NATIVE_PLAYER_ON_FALLBACK="${FREEZE_NATIVE_PLAYER_ON_FALLBACK:-1}"
FREEZE_NATIVE_PLAYER_ON_THINK="${FREEZE_NATIVE_PLAYER_ON_THINK:-1}"
PAUSE_NATIVE_ASR_DURING_LLM="${PAUSE_NATIVE_ASR_DURING_LLM:-0}"
MASTER_RESTORE_VALUE=""
LLM_SESSION_MASTER_TARGET=""
FOLLOWUP_VAD_PID=""
HOOK_WATCHDOG_PID=""
CURRENT_SESSION_ID=""
NATIVE_PLAYER_FROZEN=0
NATIVE_ASR_RESTART_NEEDED=0
NATIVE_FOLLOWUP_MARKED=0
STATE="BOOT"
LAST_LOG_SEC=""
LAST_LOG_MS=0
LED_RGB="/sys/devices/i2c-1/1-003c/led_rgb"
LED_IDS="0 1 2 3 4 5 6 7 8 9 10 11"
LED_BLUE=16711680

make_log_ts() {
    local base sec ms
    sec=$(date +%s)
    base=$(date +%H:%M:%S)
    ms=$(awk '{ split($1, a, "."); printf "%03d", substr((a[2] "000"), 1, 3) }' /proc/uptime 2>/dev/null)
    ms="${ms:-000}"
    if [ "$sec" = "$LAST_LOG_SEC" ] && [ "$ms" -le "$LAST_LOG_MS" ] 2>/dev/null; then
        ms=$((LAST_LOG_MS + 1))
        [ "$ms" -gt 999 ] && ms=999
        ms=$(printf "%03d" "$ms")
    fi
    LAST_LOG_SEC="$sec"
    LAST_LOG_MS="$ms"
    LOG_TS="${base}.${ms:-000}"
}

log() {
    make_log_ts
    echo "[$LOG_TS] $*"
}

monotonic_ms() {
    awk '{ printf "%d", ($1 * 1000) }' /proc/uptime 2>/dev/null
}

elapsed_s() {
    local start_ms="$1"
    local now_ms

    now_ms=$(monotonic_ms)
    awk -v n="$now_ms" -v s="$start_ms" 'BEGIN { printf "%.2f", (n - s) / 1000 }'
}

set_state() {
    local next="$1"
    [ "$STATE" = "$next" ] && return 0
    log "[STATE] $STATE -> $next"
    STATE="$next"
}

led_set_all() {
    local color="$1"
    [ -w "$LED_RGB" ] || return 0
    LED_RGB_PATH="$LED_RGB" LED_IDS_LIST="$LED_IDS" LED_COLOR="$color" \
        timeout 2 sh -c 'for i in $LED_IDS_LIST; do echo "$i $LED_COLOR" > "$LED_RGB_PATH" 2>/dev/null; done' \
        >/dev/null 2>&1 &
}

led_on()  { led_set_all "$LED_BLUE"; }
led_off() { led_set_all 0; }

setup_audio() {
    if [ ! -d /dev/snd ]; then
        mkdir -p /dev/snd
        mknod /dev/snd/controlC0 c 116 0 2>/dev/null
        mknod /dev/snd/pcmC0D0p c 116 16 2>/dev/null
        mknod /dev/snd/pcmC0D1p c 116 17 2>/dev/null
        mknod /dev/snd/pcmC0D0c c 116 24 2>/dev/null
        mknod /dev/snd/pcmC0D2c c 116 26 2>/dev/null
        mknod /dev/snd/timer   c 116 33 2>/dev/null
    fi
    amixer -c 0 sset 'Hard Mute' off 2>/dev/null
    amixer -c 0 sset 'Ch1' unmute 2>/dev/null
    amixer -c 0 sset 'Ch2' unmute 2>/dev/null
}

root_device() {
    awk '$2 == "/" {print $1; exit}' /proc/mounts 2>/dev/null
}

is_system1_root() {
    [ "$(root_device)" = "/dev/mtdblock5" ]
}

restore_audio_capture_overlays() {
    local i
    for i in 1 2 3 4 5; do
        umount -l /etc/asound.conf 2>/dev/null
        umount -l /usr/lib/libxaudio_engine.so 2>/dev/null
    done
    rm -f /tmp/dsnoop_ready
}

should_setup_dsnoop() {
    case "$AUDIO_CAPTURE_SETUP" in
        1|yes|true|on)
            return 0
            ;;
        0|no|false|off)
            return 1
            ;;
        auto|"")
            # boot1/system1 uses the pristine native audio path. The dsnoop and
            # libxaudio_engine overlay used on system0 can make native recorder
            # crash there, so keep boot1 native unless explicitly overridden.
            is_system1_root && return 1
            return 0
            ;;
        *)
            log "[SETUP] unknown AUDIO_CAPTURE_SETUP=$AUDIO_CAPTURE_SETUP, use auto"
            is_system1_root && return 1
            return 0
            ;;
    esac
}

apply_system_defaults() {
    if is_system1_root; then
        FOLLOWUP_ENABLED="$SYSTEM1_FOLLOWUP_ENABLED"
        if [ "$FOLLOWUP_ASR_ENGINE" = "native" ]; then
            FOLLOWUP_ASR_ENGINE="$SYSTEM1_FOLLOWUP_ASR_ENGINE"
        fi
        if [ "$FOLLOWUP_WINDOW_CAPTURE_DEV" = "Capture" ]; then
            FOLLOWUP_WINDOW_CAPTURE_DEV="$SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_DEV"
        fi
        if [ "$FOLLOWUP_WINDOW_CAPTURE_FORMAT" = "S16_LE" ]; then
            FOLLOWUP_WINDOW_CAPTURE_FORMAT="$SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_FORMAT"
        fi
        if [ "$FOLLOWUP_WINDOW_CAPTURE_RATE" = "16000" ]; then
            FOLLOWUP_WINDOW_CAPTURE_RATE="$SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_RATE"
        fi
        if [ "$FOLLOWUP_WINDOW_CAPTURE_CHANNELS" = "1" ]; then
            FOLLOWUP_WINDOW_CAPTURE_CHANNELS="$SYSTEM1_FOLLOWUP_WINDOW_CAPTURE_CHANNELS"
        fi
    fi
}

setup_dsnoop() {
    if [ -f /tmp/dsnoop_ready ] && grep -q 'pcm.Capture' /etc/asound.conf 2>/dev/null; then
        return 0
    fi

    log "[SETUP] 配置 dsnoop Capture..."

    for i in 1 2 3 4 5; do
        umount /etc/asound.conf 2>/dev/null
        umount /usr/lib/libxaudio_engine.so 2>/dev/null
    done

    cp /etc/asound.conf /tmp/asound_orig.conf
    cp /tmp/asound_orig.conf /tmp/asound_new.conf
    cat >> /tmp/asound_new.conf << 'ALSAEOF'
pcm.Capture {
    type plug
    slave.pcm {
        type dsnoop
        ipc_key 1025
        ipc_perm 0666
        slave {
            pcm "hw:0,2"
            rate 48000
            format S32_LE
            channels 8
            period_size 512
            buffer_size 4096
        }
    }
}
pcm.noop {
    type plug
    slave.pcm Capture
}
pcm.KwsCapture {
    type plug
    slave.pcm Capture
}
ALSAEOF

    mount --bind /tmp/asound_new.conf /etc/asound.conf 2>/dev/null

    if [ ! -f /tmp/libxaudio_engine_patched.so ]; then
        cp /usr/lib/libxaudio_engine.so /tmp/libxaudio_engine_patched.so
        echo -n -e 'noop\x00\x00' | dd of=/tmp/libxaudio_engine_patched.so \
            bs=1 count=6 seek=700428 conv=notrunc 2>/dev/null
    fi
    mount --bind /tmp/libxaudio_engine_patched.so /usr/lib/libxaudio_engine.so 2>/dev/null

    for pid in $(pidof mipns-xiaomi 2>/dev/null); do
        kill -9 "$pid" 2>/dev/null
    done
    sleep 1
    /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" $MIPNS_ARGS >/tmp/native_mipns.log 2>&1 &
    sleep 2

    touch /tmp/dsnoop_ready
    log "[SETUP] dsnoop Capture 就绪"
}

get_master_volume() {
    amixer -c 0 sget Master 2>/dev/null | awk '/Mono:/ {print $2; exit}'
}

get_native_media_volume() {
    ubus -t 1 call mediaplayer get_media_volume 2>/dev/null \
        | grep -o '"volume"[[:space:]]*:[[:space:]]*[0-9]*' \
        | grep -o '[0-9]*' | head -1
}

set_master_volume() {
    local vol="$1"
    [ -n "$vol" ] || return 0
    amixer -c 0 sset Master "$vol" >/dev/null 2>&1
}

calc_llm_master_volume() {
    local media_vol media_target current_target target

    case "$LLM_MASTER_VOLUME" in
        ""|"follow"|"none")
            echo ""
            return 0
            ;;
        "auto")
            if [ -n "$LLM_SESSION_MASTER_TARGET" ]; then
                log "[AUDIO] reuse session LLM Master=$LLM_SESSION_MASTER_TARGET" >&2
                echo "$LLM_SESSION_MASTER_TARGET"
                return 0
            fi

            target=0
            media_vol=$(get_native_media_volume)
            if [ -n "$media_vol" ]; then
                media_target=$((media_vol * LLM_MASTER_SCALE / 100))
                target="$media_target"
            fi

            if [ -n "$MASTER_RESTORE_VALUE" ]; then
                current_target=$((MASTER_RESTORE_VALUE * LLM_MASTER_CURRENT_SCALE / 100))
                [ "$current_target" -gt "$target" ] && target="$current_target"
            fi

            if [ "$target" -le 0 ] 2>/dev/null; then
                echo ""
                return 0
            fi

            [ "$target" -lt "$LLM_MASTER_MIN" ] && target="$LLM_MASTER_MIN"
            [ "$target" -gt "$LLM_MASTER_MAX" ] && target="$LLM_MASTER_MAX"
            log "[AUDIO] native media volume=${media_vol:-unknown} current Master=${MASTER_RESTORE_VALUE:-unknown} -> LLM Master=$target" >&2
            echo "$target"
            return 0
            ;;
        *)
            echo "$LLM_MASTER_VOLUME"
            return 0
            ;;
    esac
}

apply_llm_master_volume() {
    local target
    if [ -z "$MASTER_RESTORE_VALUE" ]; then
        MASTER_RESTORE_VALUE=$(get_master_volume)
    fi
    target=$(calc_llm_master_volume)

    if [ -z "$target" ]; then
        log "[AUDIO] follow native Master=${MASTER_RESTORE_VALUE:-unknown}"
        return 0
    fi

    if [ -n "$MASTER_RESTORE_VALUE" ] && [ "$target" -lt "$MASTER_RESTORE_VALUE" ] 2>/dev/null; then
        log "[AUDIO] keep current Master floor $target -> $MASTER_RESTORE_VALUE"
        target="$MASTER_RESTORE_VALUE"
    fi

    if [ "$LLM_MASTER_VOLUME" = "auto" ] && [ -z "$LLM_SESSION_MASTER_TARGET" ]; then
        LLM_SESSION_MASTER_TARGET="$target"
    fi

    log "[AUDIO] set LLM Master ${MASTER_RESTORE_VALUE:-unknown} -> $target"
    set_master_volume "$target"
}

restore_llm_master_volume() {
    if [ -n "$MASTER_RESTORE_VALUE" ]; then
        log "[AUDIO] restore native Master=$MASTER_RESTORE_VALUE"
        set_master_volume "$MASTER_RESTORE_VALUE"
        MASTER_RESTORE_VALUE=""
    fi
    LLM_SESSION_MASTER_TARGET=""
}

stop_our_assistants() {
    killall kws 2>/dev/null
    killall tail 2>/dev/null
    killall curl 2>/dev/null
    killall aplay 2>/dev/null
    killall arecord 2>/dev/null
    ps | grep -E 'stream_client.sh|wake_monitor.sh|vad_record.sh|native_client.sh|native_first_observer.sh' | grep -v grep | awk '{print $1}' | xargs -r kill -9 2>/dev/null
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE" 2>/dev/null)
        [ -n "$pid" ] && [ "$pid" != "$$" ] && kill -9 "$pid" 2>/dev/null
    fi
    ps | awk -v self="$$" '$1 != self && (($5 == "sh" && $6 == "/data/native_first_client.sh") || ($5 ~ /^\{native_first/ && $6 == "/bin/sh" && $7 ~ /^\/data\/native_first_client/)) { print $1 }' \
        | xargs -r kill -9 2>/dev/null
    rm -f /tmp/stream_fifo /tmp/native_wakeup_event.fifo "$EVENT_FIFO" "$FOLLOWUP_ARM_FILE"
}

restore_hook() {
    while mount | grep -q ' on /bin/wakeup.sh '; do
        umount /bin/wakeup.sh 2>/dev/null
        sleep 0.1
    done
}

ensure_original_wakeup() {
    if [ -f "$ORIG_WAKEUP" ] && ! grep -q 'NATIVE_WAKE_EVENT' "$ORIG_WAKEUP" 2>/dev/null; then
        return 0
    fi
    if cp /bin/wakeup.sh "$ORIG_WAKEUP" 2>/dev/null; then
        chmod +x "$ORIG_WAKEUP" 2>/dev/null
        log "[HOOK] saved original wakeup -> $ORIG_WAKEUP"
        return 0
    fi
    log "[HOOK] save original wakeup failed: /bin/wakeup.sh -> $ORIG_WAKEUP"
    return 1
}

install_hook() {
    restore_hook
    ensure_original_wakeup || return 1

    cat > "$HOOK_WAKEUP" << 'EOF'
#!/bin/sh
CONFIG_FILE="${CONFIG_FILE:-/data/native_first.env}"
[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"
EVENT_FIFO="${EVENT_FIFO:-/tmp/native_first_event.fifo}"
EVENT_LOG="${EVENT_LOG:-/tmp/native_first_events.log}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"
PLAYER_FROZEN_MARKER="${PLAYER_FROZEN_MARKER:-/tmp/native_first_player_frozen}"
BUSY_MARKER="${BUSY_MARKER:-/tmp/native_first_busy}"
NATIVE_REPLAY_CANCEL_MARKER="${NATIVE_REPLAY_CANCEL_MARKER:-/tmp/native_first_replay_cancel}"
FREEZE_NATIVE_PLAYER_ON_THINK="${FREEZE_NATIVE_PLAYER_ON_THINK:-1}"
WAKE_ON_THINK_SYSTEM1="${WAKE_ON_THINK_SYSTEM1:-1}"

log_ts() {
    local base ms
    base=$(date +%H:%M:%S)
    ms=$(awk '{ split($1, a, "."); printf "%03d", substr((a[2] "000"), 1, 3) }' /proc/uptime 2>/dev/null)
    echo "${base}.${ms:-000}"
}

echo "[$(log_ts)] wakeup.sh $*" >> "$EVENT_LOG"

case "$1" in
    WuW|WuW_first|WuW_oneshot)
        ts=$(date +%s)
        echo "[$(log_ts)] NATIVE_WAKE_EVENT args=$* ts=$ts" >> "$EVENT_LOG"
        if [ -f "$NATIVE_REPLAY_CANCEL_MARKER" ]; then
            rm -f "$NATIVE_REPLAY_CANCEL_MARKER"
            ubus -t 1 call mediaplayer player_play_operation '{"action":"stop"}' >/dev/null 2>&1
            ubus -t 1 call mediaplayer media_control '{"player":"mediaplayer","action":"stop"}' >/dev/null 2>&1
            ubus -t 1 call mediaplayer player_reset '{}' >/dev/null 2>&1
            echo "[$(log_ts)] NATIVE_REPLAY_CANCEL_ON_WAKE args=$* ts=$ts" >> "$EVENT_LOG"
        fi
        if [ -f "$BUSY_MARKER" ]; then
            echo "[$(log_ts)] NATIVE_WAKE_IGNORED_BUSY args=$* ts=$ts" >> "$EVENT_LOG"
        elif [ -p "$EVENT_FIFO" ]; then
            ( echo "WuW $ts" > "$EVENT_FIFO" 2>/dev/null ) &
        fi
        ;;
    think)
        ts=$(date +%s)
        echo "[$(log_ts)] NATIVE_WAKE_EVENT args=$* ts=$ts" >> "$EVENT_LOG"
        if [ -f "$BUSY_MARKER" ]; then
            echo "[$(log_ts)] NATIVE_THINK_IGNORED_BUSY args=$*" >> "$EVENT_LOG"
        else
            root_dev=$(awk '$2 == "/" {print $1; exit}' /proc/mounts 2>/dev/null)
            if [ "$WAKE_ON_THINK_SYSTEM1" = "1" ] && [ "$root_dev" = "/dev/mtdblock5" ] && [ -p "$EVENT_FIFO" ]; then
                ( echo "think $ts" > "$EVENT_FIFO" 2>/dev/null ) &
                echo "[$(log_ts)] NATIVE_WAKE_EVENT_FROM_THINK root=$root_dev ts=$ts" >> "$EVENT_LOG"
            fi
            if [ "$root_dev" = "/dev/mtdblock5" ]; then
                echo "[$(log_ts)] NATIVE_PRE_FREEZE_SKIP_SYSTEM1 args=$*" >> "$EVENT_LOG"
            elif [ "$FREEZE_NATIVE_PLAYER_ON_THINK" = "1" ]; then
                killall -STOP mediaplayer 2>/dev/null
                date +%s > "$PLAYER_FROZEN_MARKER"
                echo "[$(log_ts)] NATIVE_PRE_FREEZE args=$*" >> "$EVENT_LOG"
            fi
        fi
        ;;
    ready|bf|bf_end|noangle|noangle_end|multirounds)
        echo "[$(log_ts)] NATIVE_WAKE_EVENT args=$*" >> "$EVENT_LOG"
        ;;
esac

if [ -x "$ORIG_WAKEUP" ]; then
    exec "$ORIG_WAKEUP" "$@"
fi
exit 0
EOF
    chmod +x "$HOOK_WAKEUP"
    if mount --bind "$HOOK_WAKEUP" /bin/wakeup.sh; then
        log "[HOOK] mounted /bin/wakeup.sh -> $HOOK_WAKEUP"
    else
        log "[HOOK] mount failed ret=$?"
        return 1
    fi
}

hook_mounted() {
    mount | grep -q ' on /bin/wakeup.sh '
}

ensure_hook_mounted() {
    hook_mounted && return 0
    log "[HOOK] missing，重新挂载 /bin/wakeup.sh"
    install_hook
}

start_hook_watchdog() {
    (
        while true; do
            sleep 2
            ensure_hook_mounted
        done
    ) &
    HOOK_WATCHDOG_PID="$!"
    log "[HOOK] watchdog pid=$HOOK_WATCHDOG_PID"
}

start_mipns() {
    local pids count keep pid cmd

    pids=$(pidof mipns-xiaomi 2>/dev/null)
    count=$(echo "$pids" | wc -w 2>/dev/null)
    count="${count:-0}"
    if [ "$count" -eq 0 ] 2>/dev/null; then
        /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" $MIPNS_ARGS >/tmp/native_mipns.log 2>&1 &
        return 0
    fi

    keep=""
    for pid in $pids; do
        cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
        if echo "$cmd" | grep -q -- "-r opus32 -l"; then
            keep="$pid"
            break
        fi
    done
    [ -n "$keep" ] || keep=$(echo "$pids" | awk '{print $1}')

    if [ "$count" -gt 1 ] 2>/dev/null; then
        log "[NATIVE] multiple mipns-xiaomi detected ($count)，keep pid=$keep"
    fi
    for pid in $pids; do
        [ "$pid" = "$keep" ] || kill -9 "$pid" 2>/dev/null
    done
    kill -CONT "$keep" 2>/dev/null
}

restart_mipns_single() {
    local pids pid cmd

    pids=$(pidof mipns-xiaomi 2>/dev/null)
    for pid in $pids; do
        cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
        if ! echo "$cmd" | grep -q -- "-r opus32 -l"; then
            kill -9 "$pid" 2>/dev/null
        fi
    done
    sleep 1
    if pidof mipns-xiaomi >/dev/null 2>&1; then
        start_mipns
    else
        /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" $MIPNS_ARGS >/tmp/native_mipns.log 2>&1 &
    fi
}

extract_first_value() {
    # Input is the raw nlp_result_get output. Values are nested as escaped JSON,
    # for example: domain\\\": \\\"smartMiot\\\".
    local key="$1"
    grep -o "${key}[^,}]*: [^,}]*" | head -1 | awk -F'\\\\\\"' '{print $3}' | sed 's/\\*$//'
}

json_escape() {
    sed 's/\\/\\\\/g; s/"/\\"/g'
}

json_unicode_decode() {
    awk '
function hv(c) { return index("0123456789abcdef", tolower(c)) - 1 }
function emit(n) {
    if (n < 128) printf "%c", n;
    else if (n < 2048) printf "%c%c", 192 + int(n / 64), 128 + (n % 64);
    else printf "%c%c%c", 224 + int(n / 4096), 128 + (int(n / 64) % 64), 128 + (n % 64);
}
{
    for (i = 1; i <= length($0); i++) {
        if (substr($0, i, 2) == "\\u" && i + 5 <= length($0)) {
            h = substr($0, i + 2, 4);
            n = 0;
            ok = 1;
            for (j = 1; j <= 4; j++) {
                v = hv(substr(h, j, 1));
                if (v < 0) ok = 0;
                n = n * 16 + v;
            }
            if (ok) {
                emit(n);
                i += 5;
                continue;
            }
        }
        printf "%s", substr($0, i, 1);
    }
    printf "\n";
}'
}

json_text_unescape() {
    json_unicode_decode | sed 's/\\"/"/g; s/\\\\/\\/g'
}

reset_native_result() {
    RESULT_SOURCE=""
    RESULT_TS=""
    RESULT_DOMAIN=""
    RESULT_ACTION=""
    RESULT_QUERY=""
    RESULT_SPEAK=""
}

select_native_result_source() {
    case "$NATIVE_RESULT_SOURCE" in
        ubus_nlp_result|aivs_lab_instruction)
            echo "$NATIVE_RESULT_SOURCE"
            ;;
        auto|*)
            if is_system1_root && [ "$NATIVE_AIVS_LAB_RESULT_SYSTEM1" = "1" ]; then
                echo "aivs_lab_instruction"
            else
                echo "ubus_nlp_result"
            fi
            ;;
    esac
}

get_aivs_lab_latest_dialog_id() {
    [ -f "$AIVS_LAB_INSTRUCTION_LOG" ] || return 0
    tail -n "$AIVS_LAB_LOOKBACK_LINES" "$AIVS_LAB_INSTRUCTION_LOG" 2>/dev/null \
        | sed -n 's/.*"dialog_id":"\([^"]*\)".*/\1/p' \
        | tail -1
}

init_native_result_state() {
    local source dialog_id

    source=$(select_native_result_source)
    if [ "$source" = "aivs_lab_instruction" ]; then
        dialog_id=$(get_aivs_lab_latest_dialog_id)
        if [ -n "$dialog_id" ]; then
            echo "$dialog_id" > "$AIVS_LAB_LAST_DIALOG_FILE"
            log "Native result: initialized aivs_lab last_dialog=$dialog_id"
        fi
    fi
}

get_native_result_ubus() {
    local raw="$1"
    local item

    reset_native_result

    # nlp_result_get returns a history array. The newest item may contain only
    # timestamp/asr and no nlp, so all fields must be extracted from the same
    # first item that actually has an nlp payload.
    item=$(echo "$raw" | sed 's/}, {/\n/g' | grep '\\"nlp\\"' | head -1)
    [ -n "$item" ] || return 0

    RESULT_TS=$(echo "$item" | grep -o 'timestamp[^0-9]*[0-9][0-9]*' | head -1 | grep -o '[0-9][0-9]*' | head -1)
    RESULT_DOMAIN=$(echo "$item" | extract_first_value domain)
    RESULT_ACTION=$(echo "$item" | extract_first_value action)
    RESULT_QUERY=$(echo "$item" | extract_first_value query)
    RESULT_SPEAK=$(echo "$item" | extract_first_value to_speak)
    RESULT_SOURCE="ubus_nlp_result"
}

get_native_result_aivs_lab() {
    local new_lines dialog_id dialog_lines raw_query raw_speak
    local last_dialog

    reset_native_result

    [ "$NATIVE_AIVS_LAB_RESULT_SYSTEM1" = "1" ] || return 1
    is_system1_root || return 1
    [ -f "$AIVS_LAB_INSTRUCTION_LOG" ] || return 1

    new_lines=$(tail -n "$AIVS_LAB_LOOKBACK_LINES" "$AIVS_LAB_INSTRUCTION_LOG" 2>/dev/null)
    [ -n "$new_lines" ] || return 1

    dialog_id=$(printf '%s\n' "$new_lines" | sed -n 's/.*"dialog_id":"\([^"]*\)".*/\1/p' | tail -1)
    [ -n "$dialog_id" ] || return 1

    last_dialog=$(cat "$AIVS_LAB_LAST_DIALOG_FILE" 2>/dev/null)
    [ "$dialog_id" = "$last_dialog" ] && return 1

    dialog_lines=$(printf '%s\n' "$new_lines" | grep "\"dialog_id\":\"$dialog_id\"")
    [ -n "$dialog_lines" ] || return 1

    raw_query=$(printf '%s\n' "$dialog_lines" \
        | sed -n 's/.*"name":"RecognizeResult".*"is_final":true.*"text":"\([^"]*\)".*/\1/p' \
        | tail -1)
    [ -n "$raw_query" ] || raw_query=$(printf '%s\n' "$dialog_lines" \
        | sed -n 's/.*"name":"RecognizeResult".*"text":"\([^"]*\)".*/\1/p' \
        | tail -1)
    raw_speak=$(printf '%s\n' "$dialog_lines" \
        | sed -n 's/.*"name":"Speak".*"text":"\([^"]*\)".*/\1/p' \
        | tail -1)

    [ -n "$raw_query$raw_speak" ] || return 1

    [ -n "$raw_query" ] && RESULT_QUERY=$(printf '%s\n' "$raw_query" | json_text_unescape)
    [ -n "$raw_speak" ] && RESULT_SPEAK=$(printf '%s\n' "$raw_speak" | json_text_unescape)

    if [ -n "$RESULT_QUERY" ] && echo "$RESULT_QUERY" | grep -Eq "$DIRECT_LLM_QUERY_PATTERNS"; then
        RESULT_TS=$(date +%s)
        RESULT_DOMAIN="michat"
        RESULT_ACTION="model"
        RESULT_SOURCE="aivs_lab_instruction"
        echo "$dialog_id" > "$AIVS_LAB_LAST_DIALOG_FILE"
        return 0
    fi

    if [ -n "$RESULT_QUERY" ] && [ -n "$RESULT_SPEAK" ] && is_unsupported_result; then
        RESULT_TS=$(date +%s)
        RESULT_DOMAIN="michat"
        RESULT_ACTION="model"
        RESULT_SOURCE="aivs_lab_instruction"
        echo "$dialog_id" > "$AIVS_LAB_LAST_DIALOG_FILE"
        return 0
    fi

    return 1
}

native_followup_mark_multirounds() {
    local force="${1:-0}"

    [ "$NATIVE_FOLLOWUP_PRE_MULTIROUNDS" = "1" ] || return 0
    [ "$force" != "1" ] && [ "$NATIVE_FOLLOWUP_MARKED" = "1" ] && return 0
    NATIVE_FOLLOWUP_MARKED=1
    log "[NATIVE_FOLLOWUP] pre multirounds trigger=$NATIVE_FOLLOWUP_MULTIROUNDS_TRIGGER"
    case "$NATIVE_FOLLOWUP_MULTIROUNDS_TRIGGER" in
        pns6)
            ubus -t 1 call pnshelper event_notify '{"src":3,"event":6}' >/dev/null 2>&1
            ;;
        oneshot)
            ubus -t 1 call pnshelper oneshot_set '{"open":true}' >/dev/null 2>&1
            ;;
        wakeup)
            [ -x "$ORIG_WAKEUP" ] && "$ORIG_WAKEUP" multirounds >/dev/null 2>&1
            ;;
        both6)
            ubus -t 1 call pnshelper event_notify '{"src":3,"event":6}' >/dev/null 2>&1
            [ -x "$ORIG_WAKEUP" ] && "$ORIG_WAKEUP" multirounds >/dev/null 2>&1
            ;;
        both)
            ubus -t 1 call pnshelper event_notify '{"src":3,"event":4,"detail":"pre_multirounds"}' >/dev/null 2>&1
            [ -x "$ORIG_WAKEUP" ] && "$ORIG_WAKEUP" multirounds >/dev/null 2>&1
            ;;
        pns|*)
            ubus -t 1 call pnshelper event_notify '{"src":3,"event":4,"detail":"pre_multirounds"}' >/dev/null 2>&1
            ;;
    esac
}

native_followup_tts_start() {
    [ "$NATIVE_FOLLOWUP_TTS_NOTIFY" = "1" ] || return 0
    ubus -t 1 call pnshelper event_notify '{"src":3,"event":12}' >/dev/null 2>&1
    log "[NATIVE_FOLLOWUP] notify local tts start"
}

native_followup_tts_end() {
    [ "$NATIVE_FOLLOWUP_TTS_NOTIFY" = "1" ] || return 0
    ubus -t 1 call pnshelper event_notify '{"src":3,"event":13}' >/dev/null 2>&1
    log "[NATIVE_FOLLOWUP] notify local tts end"
    if [ "$NATIVE_FOLLOWUP_TRIGGER_AFTER_TTS_END" = "1" ]; then
        log "[NATIVE_FOLLOWUP] trigger multirounds after tts end"
        native_followup_mark_multirounds 1
    fi
}

extract_aivs_latest_final_text_after() {
    local last_dialog="$1"
    local ignore_text="$2"
    local new_lines dialog_id dialog_lines raw_text text

    FOLLOWUP_TEXT=""
    [ -f "$AIVS_LAB_INSTRUCTION_LOG" ] || return 1

    new_lines=$(tail -n "$AIVS_LAB_LOOKBACK_LINES" "$AIVS_LAB_INSTRUCTION_LOG" 2>/dev/null)
    [ -n "$new_lines" ] || return 1

    dialog_id=$(printf '%s\n' "$new_lines" | sed -n 's/.*"dialog_id":"\([^"]*\)".*/\1/p' | tail -1)
    [ -n "$dialog_id" ] || return 1
    [ "$dialog_id" = "$last_dialog" ] && return 1

    dialog_lines=$(printf '%s\n' "$new_lines" | grep "\"dialog_id\":\"$dialog_id\"")
    [ -n "$dialog_lines" ] || return 1

    raw_text=$(printf '%s\n' "$dialog_lines" \
        | sed -n 's/.*"name":"RecognizeResult".*"is_final":true.*"text":"\([^"]*\)".*/\1/p' \
        | tail -1)
    [ -n "$raw_text" ] || return 1

    text=$(printf '%s\n' "$raw_text" | json_text_unescape)
    [ -n "$text" ] || return 1
    [ "$text" = "$ignore_text" ] && return 1

    FOLLOWUP_TEXT="$text"
    echo "$dialog_id" > "$AIVS_LAB_LAST_DIALOG_FILE"
    return 0
}

wait_native_followup_text() {
    local last_dialog="$1"
    local ignore_text="$2"
    local max_ticks waited_ticks=0

    max_ticks=$(awk -v s="$NATIVE_FOLLOWUP_POLL_SECONDS" -v p="$NATIVE_FOLLOWUP_POLL_INTERVAL" 'BEGIN { printf "%d", (s / p) }')
    log "[NATIVE_FOLLOWUP] wait native ASR ${NATIVE_FOLLOWUP_POLL_SECONDS}s last_dialog=${last_dialog:-none}"
    while [ "$waited_ticks" -lt "$max_ticks" ]; do
        sleep "$NATIVE_FOLLOWUP_POLL_INTERVAL"
        if extract_aivs_latest_final_text_after "$last_dialog" "$ignore_text"; then
            log "[NATIVE_FOLLOWUP] ASR text=$FOLLOWUP_TEXT"
            return 0
        fi
        waited_ticks=$((waited_ticks + 1))
    done
    log "[NATIVE_FOLLOWUP] timeout/no text"
    return 1
}

get_native_result() {
    local source="$1"
    local raw

    case "$source" in
        aivs_lab_instruction)
            get_native_result_aivs_lab && return 0
            reset_native_result
            return 1
            ;;
        ubus_nlp_result|*)
            raw=$(ubus -t "$NATIVE_UBUS_TIMEOUT" call mibrain nlp_result_get)
            get_native_result_ubus "$raw"
            [ -n "$RESULT_TS" ] && [ -n "$RESULT_DOMAIN" ]
            return $?
            ;;
    esac
}

start_native_replay_cancel_window() {
    local token

    [ "$NATIVE_REPLAY_CANCEL_ON_WAKE" = "1" ] || return 1
    token="$$-$(monotonic_ms)"
    printf '%s\n' "$token" > "$NATIVE_REPLAY_CANCEL_MARKER" 2>/dev/null || return 1
    REPLAY_CANCEL_TOKEN="$token"
    (
        sleep "$NATIVE_REPLAY_CANCEL_WINDOW"
        current=$(cat "$NATIVE_REPLAY_CANCEL_MARKER" 2>/dev/null)
        [ "$current" = "$token" ] && rm -f "$NATIVE_REPLAY_CANCEL_MARKER"
    ) &
    return 0
}

is_native_replay_cancelled() {
    local current

    [ -n "$REPLAY_CANCEL_TOKEN" ] || return 1
    current=$(cat "$NATIVE_REPLAY_CANCEL_MARKER" 2>/dev/null)
    [ "$current" != "$REPLAY_CANCEL_TOKEN" ]
}

should_cancel_native_replay_on_wake() {
    [ "$NATIVE_REPLAY_CANCEL_ON_WAKE" = "1" ] || return 1
    echo " $NATIVE_REPLAY_CANCEL_DOMAINS " | grep -q " $RESULT_DOMAIN "
}

native_tts_speak() {
    local text="$1"
    [ -n "$text" ] || return 0

    safe_text=$(printf '%s' "$text" | json_escape)
    log "[NATIVE] replay native speak: $text"
    ubus -t 8 call mibrain text_to_speech \
        "{\"text\":\"$safe_text\",\"caller\":\"native_first\",\"vendor\":\"\",\"codec\":\"mp3\",\"volume\":100,\"save\":0,\"play\":1}" \
        >/dev/null 2>&1
}

native_tts_speak_cancellable() {
    local text="$1"

    REPLAY_CANCEL_TOKEN=""
    if start_native_replay_cancel_window; then
        log "[NATIVE] replay cancel window: grace=${NATIVE_REPLAY_CANCEL_GRACE}s window=${NATIVE_REPLAY_CANCEL_WINDOW}s"
        sleep "$NATIVE_REPLAY_CANCEL_GRACE"
        if is_native_replay_cancelled; then
            log "[NATIVE] replay cancelled before speak: $text"
            return 0
        fi
    fi

    native_tts_speak "$text"
}

handle_native_success_speak() {
    if [ -z "$RESULT_SPEAK" ]; then
        resume_native_player 0
        return 0
    fi

    case "$NATIVE_REPLAY_SUCCESS_SPEAK" in
        1|yes|true)
            resume_native_player 0
            if should_cancel_native_replay_on_wake; then
                native_tts_speak_cancellable "$RESULT_SPEAK"
            else
                native_tts_speak "$RESULT_SPEAK"
            fi
            ;;
        auto)
            resume_native_player 0
            log "[NATIVE] success speak auto replay after ${NATIVE_REPLAY_SUCCESS_DELAY}s"
            should_cancel_native_replay_on_wake && start_native_replay_cancel_window || true
            sleep "$NATIVE_REPLAY_SUCCESS_DELAY"
            if is_native_replay_cancelled; then
                log "[NATIVE] replay cancelled before speak: $RESULT_SPEAK"
            else
                native_tts_speak "$RESULT_SPEAK"
            fi
            ;;
        *)
            resume_native_player 0
            ;;
    esac
}

is_unsupported_result() {
    echo "$RESULT_SPEAK" | grep -Eq "$UNSUPPORTED_PATTERNS" && return 0
    [ "$RESULT_DOMAIN" = "michat" ] && [ "$RESULT_ACTION" = "model" ] && return 0
    return 1
}

is_native_success_domain() {
    echo " $NATIVE_SUCCESS_DOMAINS " | grep -q " $RESULT_DOMAIN "
}

is_ignored_query_result() {
    local compact_query item compact_item

    compact_query=$(printf '%s' "$RESULT_QUERY" | tr -d '[:space:]')
    [ -n "$compact_query" ] || return 1

    for item in $WAKE_IGNORE_QUERIES; do
        compact_item=$(printf '%s' "$item" | tr -d '[:space:]')
        [ "$compact_query" = "$compact_item" ] && return 0
    done

    return 1
}

stop_native_playback() {
    local n="${1:-1}"
    while [ "$n" -gt 0 ]; do
        ubus -t 1 call mediaplayer player_play_operation '{"action":"stop"}' >/dev/null 2>&1
        ubus -t 1 call mediaplayer media_control '{"player":"mediaplayer","action":"stop"}' >/dev/null 2>&1
        n=$((n - 1))
        [ "$n" -gt 0 ] && sleep 0.3
    done
}

stop_native_playback_guard() {
    local seconds="${1:-$STOP_NATIVE_SECONDS}"
    local loops=$((seconds * 5))
    while [ "$loops" -gt 0 ]; do
        ubus -t 1 call mediaplayer player_play_operation '{"action":"stop"}' >/dev/null 2>&1
        ubus -t 1 call mediaplayer media_control '{"player":"mediaplayer","action":"stop"}' >/dev/null 2>&1
        sleep 0.2
        loops=$((loops - 1))
    done
}

freeze_native_player() {
    [ "$FREEZE_NATIVE_PLAYER_ON_FALLBACK" = "1" ] || return 0
    killall -STOP mediaplayer 2>/dev/null
    date +%s > "$PLAYER_FROZEN_MARKER"
    NATIVE_PLAYER_FROZEN=1
    log "[NATIVE] mediaplayer frozen"
}

is_native_player_frozen() {
    [ "$NATIVE_PLAYER_FROZEN" = "1" ] && return 0
    [ -f "$PLAYER_FROZEN_MARKER" ] && return 0
    return 1
}

resume_native_player() {
    local clear_queue="${1:-1}"
    is_native_player_frozen || return 0
    killall -CONT mediaplayer 2>/dev/null
    NATIVE_PLAYER_FROZEN=0
    rm -f "$PLAYER_FROZEN_MARKER"
    log "[NATIVE] mediaplayer resumed clear_queue=$clear_queue"
    if [ "$clear_queue" = "1" ]; then
        ubus -t 1 call mediaplayer player_play_operation '{"action":"stop"}' >/dev/null 2>&1
        ubus -t 1 call mediaplayer media_control '{"player":"mediaplayer","action":"stop"}' >/dev/null 2>&1
        ubus -t 1 call mediaplayer player_reset '{}' >/dev/null 2>&1
        stop_native_playback 3
    fi
}

pause_native_asr() {
    if [ "$PAUSE_NATIVE_ASR_DURING_LLM" = "1" ]; then
        killall -STOP mipns-xiaomi 2>/dev/null
        log "[NATIVE] mipns paused for LLM followup"
    else
        log "[NATIVE] keep mipns running for followup capture"
    fi
}

resume_native_asr() {
    if [ "$NATIVE_ASR_RESTART_NEEDED" = "1" ]; then
        restart_mipns_single
        NATIVE_ASR_RESTART_NEEDED=0
        log "[NATIVE] mipns restarted after boot1 followup capture"
        return 0
    fi
    if [ "$PAUSE_NATIVE_ASR_DURING_LLM" = "1" ]; then
        killall -CONT mipns-xiaomi 2>/dev/null
        log "[NATIVE] mipns resumed"
    else
        log "[NATIVE] mipns already running"
    fi
}

prepare_followup_capture() {
    if is_system1_root && [ "$SYSTEM1_FOLLOWUP_CAPTURE_MIPNS" = "1" ]; then
        if pidof mipns-xiaomi >/dev/null 2>&1; then
            killall -9 mipns-xiaomi 2>/dev/null
            NATIVE_ASR_RESTART_NEEDED=1
            log "[NATIVE] mipns killed for boot1 followup capture"
            sleep 0.3
        fi
    fi
}

set_busy() {
    date +%s > "$BUSY_MARKER"
    log "[BUSY] on: $*"
}

clear_busy() {
    if [ -f "$BUSY_MARKER" ]; then
        rm -f "$BUSY_MARKER"
        log "[BUSY] off"
    fi
}

is_busy() {
    [ -f "$BUSY_MARKER" ]
}

record_llm_query() {
    printf '%s' "$1" > "$LAST_LLM_QUERY_FILE"
    date +%s > "$LAST_LLM_TS_FILE"
}

is_recent_duplicate_llm_query() {
    local text="$1"
    local last_text last_ts now age

    [ "$SUPPRESS_DUP_SECONDS" -gt 0 ] 2>/dev/null || return 1
    [ -f "$LAST_LLM_QUERY_FILE" ] || return 1
    [ -f "$LAST_LLM_TS_FILE" ] || return 1

    last_text=$(cat "$LAST_LLM_QUERY_FILE" 2>/dev/null)
    last_ts=$(cat "$LAST_LLM_TS_FILE" 2>/dev/null)
    now=$(date +%s)
    [ -n "$last_ts" ] || return 1

    age=$((now - last_ts))
    [ "$age" -le "$SUPPRESS_DUP_SECONDS" ] || return 1
    [ "$text" = "$last_text" ] || return 1
    return 0
}

finish_llm_playback() {
    resume_native_player 1
    restore_llm_master_volume
    clear_busy
}

start_followup_vad_prearm() {
    local timeout

    [ "$FOLLOWUP_PREARM" = "1" ] || return 0
    [ -z "$FOLLOWUP_VAD_PID" ] || return 0

    if [ "$FOLLOWUP_RECORD_MODE" = "window" ]; then
        timeout="$FOLLOWUP_WINDOW_SECONDS"
    else
        timeout="$FOLLOWUP_TIMEOUT"
    fi
    rm -f "$FOLLOWUP_ARM_FILE"
    log "[FOLLOWUP] prearm recorder: mode=${FOLLOWUP_RECORD_MODE} wait_playback_done timeout=${timeout}s start=$FOLLOWUP_THRESHOLD end=$FOLLOWUP_END_THRESHOLD silence=${FOLLOWUP_SILENCE_LIMIT}s"
    (
        VAD_ARM_FILE="$FOLLOWUP_ARM_FILE" \
        SPEECH_THRESHOLD="$FOLLOWUP_THRESHOLD" \
        START_HITS="$FOLLOWUP_START_HITS" \
        END_THRESHOLD="$FOLLOWUP_END_THRESHOLD" \
        START_RMS_THRESHOLD="$FOLLOWUP_START_RMS_THRESHOLD" \
        END_RMS_THRESHOLD="$FOLLOWUP_END_RMS_THRESHOLD" \
        START_ACTIVE_PERMILLE="$FOLLOWUP_START_ACTIVE_PERMILLE" \
        END_ACTIVE_PERMILLE="$FOLLOWUP_END_ACTIVE_PERMILLE" \
        IGNORE_INITIAL_CHUNKS="$FOLLOWUP_IGNORE_INITIAL_CHUNKS" \
        TAIL_RMS_THRESHOLD="$FOLLOWUP_TAIL_RMS_THRESHOLD" \
        TAIL_ACTIVE_PERMILLE="$FOLLOWUP_TAIL_ACTIVE_PERMILLE" \
        SILENCE_LIMIT="$FOLLOWUP_SILENCE_LIMIT" \
        MIN_RAW_BYTES="$FOLLOWUP_MIN_RAW_BYTES" \
        WINDOW_CAPTURE_DEV="$FOLLOWUP_WINDOW_CAPTURE_DEV" \
        WINDOW_CAPTURE_FORMAT="$FOLLOWUP_WINDOW_CAPTURE_FORMAT" \
        WINDOW_CAPTURE_RATE="$FOLLOWUP_WINDOW_CAPTURE_RATE" \
        WINDOW_CAPTURE_CHANNELS="$FOLLOWUP_WINDOW_CAPTURE_CHANNELS" \
        WINDOW_MIN_PEAK="$FOLLOWUP_WINDOW_MIN_PEAK" \
        WINDOW_MIN_RMS_THRESHOLD="$FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD" \
        WINDOW_MIN_ACTIVE_PERMILLE="$FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE" \
        sh "$VAD_SCRIPT" "$FOLLOWUP_RECORD_MODE" "$timeout"
    ) &
    FOLLOWUP_VAD_PID=$!
}

arm_followup_vad() {
    if [ -n "$FOLLOWUP_VAD_PID" ]; then
        log "[FOLLOWUP] wait ${FOLLOWUP_ARM_DELAY}s for speaker tail"
        sleep "$FOLLOWUP_ARM_DELAY"
        prepare_followup_capture
        touch "$FOLLOWUP_ARM_FILE" 2>/dev/null
        log "[FOLLOWUP] arm VAD after playback"
    fi
}

wait_or_run_followup_vad() {
    local ret timeout

    if [ -n "$FOLLOWUP_VAD_PID" ]; then
        set_state "FOLLOWUP_LISTENING"
        log "[FOLLOWUP] ${FOLLOWUP_TIMEOUT}s 内可继续追问...（VAD 已预热）"
        wait "$FOLLOWUP_VAD_PID" 2>/dev/null
        ret=$?
        FOLLOWUP_VAD_PID=""
        rm -f "$FOLLOWUP_ARM_FILE"
        return "$ret"
    fi

    set_state "FOLLOWUP_LISTENING"
    if [ "$FOLLOWUP_RECORD_MODE" = "window" ]; then
        timeout="$FOLLOWUP_WINDOW_SECONDS"
    else
        timeout="$FOLLOWUP_TIMEOUT"
    fi
    log "[FOLLOWUP] ${timeout}s 内可继续追问..."
    SPEECH_THRESHOLD="$FOLLOWUP_THRESHOLD" \
    START_HITS="$FOLLOWUP_START_HITS" \
    END_THRESHOLD="$FOLLOWUP_END_THRESHOLD" \
    START_RMS_THRESHOLD="$FOLLOWUP_START_RMS_THRESHOLD" \
    END_RMS_THRESHOLD="$FOLLOWUP_END_RMS_THRESHOLD" \
    START_ACTIVE_PERMILLE="$FOLLOWUP_START_ACTIVE_PERMILLE" \
    END_ACTIVE_PERMILLE="$FOLLOWUP_END_ACTIVE_PERMILLE" \
    IGNORE_INITIAL_CHUNKS="$FOLLOWUP_IGNORE_INITIAL_CHUNKS" \
    TAIL_RMS_THRESHOLD="$FOLLOWUP_TAIL_RMS_THRESHOLD" \
    TAIL_ACTIVE_PERMILLE="$FOLLOWUP_TAIL_ACTIVE_PERMILLE" \
    SILENCE_LIMIT="$FOLLOWUP_SILENCE_LIMIT" \
    MIN_RAW_BYTES="$FOLLOWUP_MIN_RAW_BYTES" \
    WINDOW_CAPTURE_DEV="$FOLLOWUP_WINDOW_CAPTURE_DEV" \
    WINDOW_CAPTURE_FORMAT="$FOLLOWUP_WINDOW_CAPTURE_FORMAT" \
    WINDOW_CAPTURE_RATE="$FOLLOWUP_WINDOW_CAPTURE_RATE" \
    WINDOW_CAPTURE_CHANNELS="$FOLLOWUP_WINDOW_CAPTURE_CHANNELS" \
    WINDOW_MIN_PEAK="$FOLLOWUP_WINDOW_MIN_PEAK" \
    WINDOW_MIN_RMS_THRESHOLD="$FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD" \
    WINDOW_MIN_ACTIVE_PERMILLE="$FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE" \
    sh "$VAD_SCRIPT" "$FOLLOWUP_RECORD_MODE" "$timeout"
    return $?
}

send_text_and_play() {
    local session_id="$1"
    local text="$2"
    local cleanup_mode="${3:-now}"
    local t0 t1 t2

    if [ -z "$text" ]; then
        log "[LLM] 无 query，跳过 fallback"
        return 1
    fi

    if is_recent_duplicate_llm_query "$text"; then
        log "[DUP] suppress duplicate fallback ${SUPPRESS_DUP_SECONDS}s 内重复: $text"
        resume_native_player 1
        return 0
    fi

    log "[LLM] fallback → backend=$BACKEND text=$text"
    set_state "LLM_SPEAKING"
    record_llm_query "$text"
    set_busy "llm_playing"
    apply_llm_master_volume
    freeze_native_player
    log "[NATIVE] stop native player during fallback (${STOP_NATIVE_SECONDS}s)"
    t0=$(date +%s)

    rm -f /tmp/stream_fifo
    mkfifo /tmp/stream_fifo 2>/dev/null || mknod /tmp/stream_fifo p 2>/dev/null

    curl -s --no-buffer -o /tmp/stream_fifo --max-time "$STREAM_TIMEOUT" \
        -F "message=${text}" \
        -F "session_id=${session_id}" \
        -F "backend=${BACKEND}" \
        -F "speed=1.0" \
        -F "volume=${LLM_VOLUME}" \
        "${SERVER}/api/v1/stream/text_chat" &
    CURL_PID=$!

    aplay /tmp/stream_fifo 2>/dev/null &
    APLAY_PID=$!
    if [ "$cleanup_mode" = "native_defer" ]; then
        native_followup_tts_start
    fi

    wait $CURL_PID 2>/dev/null
    t1=$(date +%s)
    log "[LLM] stream download done in $((t1 - t0))s"
    if [ "$cleanup_mode" = "defer" ]; then
        start_followup_vad_prearm
    fi
    wait $APLAY_PID 2>/dev/null
    t2=$(date +%s)
    log "[LLM] aplay done in $((t2 - t0))s (drain=$((t2 - t1))s)"
    if [ "$cleanup_mode" = "native_defer" ]; then
        native_followup_tts_end
    fi
    if [ "$cleanup_mode" = "defer" ]; then
        arm_followup_vad
    fi
    if [ "$cleanup_mode" = "defer" ] || [ "$cleanup_mode" = "native_defer" ]; then
        log "[LLM] playback done, defer cleanup for followup"
        set_state "FOLLOWUP_WINDOW"
    else
        finish_llm_playback
    fi
    rm -f /tmp/stream_fifo
}

send_voice_and_play() {
    local session_id="$1"
    local voice_file="/tmp/voice.wav"
    local size

    if [ ! -f "$voice_file" ]; then
        log "[LLM] 追问录音不存在"
        return 1
    fi

    size=$(wc -c < "$voice_file" 2>/dev/null)
    log "[LLM] followup voice → backend=$BACKEND size=${size} session=$session_id"
    set_busy "llm_playing"
    apply_llm_master_volume
    freeze_native_player

    rm -f /tmp/stream_fifo
    mkfifo /tmp/stream_fifo 2>/dev/null || mknod /tmp/stream_fifo p 2>/dev/null

    curl -s --no-buffer -o /tmp/stream_fifo --max-time "$STREAM_TIMEOUT" \
        -F "file=@${voice_file}" \
        "${SERVER}/api/v1/stream/chat?session_id=${session_id}&backend=${BACKEND}&speed=1.0&volume=${LLM_VOLUME}" &
    CURL_PID=$!

    aplay /tmp/stream_fifo 2>/dev/null &
    APLAY_PID=$!

    wait $CURL_PID 2>/dev/null
    wait $APLAY_PID 2>/dev/null
    finish_llm_playback
    rm -f /tmp/stream_fifo
}

extract_ai_service_asr_query() {
    LC_ALL=C sed -n 's/.*\\\\\\"query\\\\\\":\\\\\\"\([^\\]*\).*/\1/p' | head -1
}

transcribe_followup_voice_mac() {
    local voice_file="/tmp/voice.wav"
    local result_file="/tmp/native_followup_asr.env"

    FOLLOWUP_TEXT=""

    if [ ! -f "$voice_file" ]; then
        log "[FOLLOWUP] 追问录音不存在"
        return 1
    fi

    log "[FOLLOWUP] 发送追问录音做 ASR..."
    curl -s --max-time "$STREAM_TIMEOUT" \
        -F "session_id=${CURRENT_SESSION_ID}" \
        -F "file=@${voice_file}" \
        "${SERVER}/api/v1/route/asr" > "$result_file"

    FOLLOWUP_TEXT=$(sed -n 's/^TEXT=//p' "$result_file" | head -1)
    FOLLOWUP_ROUTE=$(sed -n 's/^ROUTE=//p' "$result_file" | head -1)
    FOLLOWUP_REASON=$(sed -n 's/^REASON=//p' "$result_file" | head -1)

    log "[FOLLOWUP] ASR text=${FOLLOWUP_TEXT:-<empty>} route=${FOLLOWUP_ROUTE:-unknown} reason=${FOLLOWUP_REASON:-unknown}"
    if [ -z "$FOLLOWUP_TEXT" ]; then
        cp "$voice_file" "/tmp/followup_empty_$(date +%s).wav" 2>/dev/null
        return 1
    fi
    return 0
}

transcribe_followup_voice_native() {
    local voice_file="/tmp/voice.wav"
    local result_file="/tmp/native_followup_ai_service.json"
    local req_id payload safe_voice raw code

    FOLLOWUP_TEXT=""
    FOLLOWUP_ROUTE=""
    FOLLOWUP_REASON=""

    if [ ! -f "$voice_file" ]; then
        log "[FOLLOWUP] 追问录音不存在"
        return 1
    fi

    req_id="native_followup_$(date +%s)"
    safe_voice=$(printf '%s' "$voice_file" | json_escape)
    payload="{\"bypass\":\"\",\"caller\":\"native_first_followup\",\"duration\":0,\"id\":\"$req_id\",\"asr\":1,\"nlp\":1,\"tts\":0,\"asr_audio\":\"$safe_voice\",\"nlp_text\":\"\",\"nlp_execute\":0,\"tts_text\":\"\",\"tts_type\":\"\",\"tts_vendor\":\"\",\"tts_volume\":80,\"tts_codec\":\"mp3\",\"tts_save\":0,\"tts_play\":0}"

    log "[FOLLOWUP] 发送追问录音给小米原生 ASR: $voice_file"
    raw=$(ubus -t "$FOLLOWUP_NATIVE_ASR_TIMEOUT" call mibrain ai_service "$payload" 2>&1)
    code=$(printf '%s' "$raw" | grep -o '"code"[[:space:]]*:[[:space:]]*-*[0-9]*' | grep -o -- '-*[0-9]*' | head -1)
    printf '%s\n' "$raw" > "$result_file"

    FOLLOWUP_TEXT=$(printf '%s' "$raw" | extract_ai_service_asr_query)
    FOLLOWUP_ROUTE="llm"
    FOLLOWUP_REASON="native_asr_ok"

    log "[FOLLOWUP] Native ASR code=${code:-unknown} text=${FOLLOWUP_TEXT:-<empty>}"
    if [ -z "$FOLLOWUP_TEXT" ]; then
        cp "$voice_file" "/tmp/followup_native_empty_$(date +%s).wav" 2>/dev/null
        FOLLOWUP_ROUTE="empty"
        FOLLOWUP_REASON="native_asr_empty"
        return 1
    fi
    if [ "$FOLLOWUP_NATIVE_MIN_QUERY_BYTES" -gt 0 ] 2>/dev/null; then
        query_bytes=$(printf '%s' "$FOLLOWUP_TEXT" | wc -c 2>/dev/null)
        query_bytes="${query_bytes:-0}"
        if [ "$query_bytes" -lt "$FOLLOWUP_NATIVE_MIN_QUERY_BYTES" ] 2>/dev/null; then
            log "[FOLLOWUP] Native ASR 文本过短，忽略 bytes=$query_bytes min=$FOLLOWUP_NATIVE_MIN_QUERY_BYTES text=$FOLLOWUP_TEXT"
            FOLLOWUP_ROUTE="empty"
            FOLLOWUP_REASON="native_asr_short"
            return 1
        fi
    fi
    return 0
}

transcribe_followup_voice() {
    case "$FOLLOWUP_ASR_ENGINE" in
        native)
            if transcribe_followup_voice_native; then
                return 0
            fi
            if [ "$FOLLOWUP_NATIVE_ASR_FALLBACK_MAC" = "1" ]; then
                log "[FOLLOWUP] Native ASR 无文本，fallback Mac ASR"
                transcribe_followup_voice_mac
                return $?
            fi
            return 1
            ;;
        mac|whisper)
            transcribe_followup_voice_mac
            return $?
            ;;
        *)
            log "[FOLLOWUP] 未知 ASR 引擎: $FOLLOWUP_ASR_ENGINE"
            return 1
            ;;
    esac
}

handle_llm_dialog() {
    local session_id="$1"
    local first_text="$2"
    local turn=1
    local ret
    local last_dialog

    CURRENT_SESSION_ID="$session_id"
    set_state "LLM_DIALOG"
    led_on
    pause_native_asr

    if [ "$FOLLOWUP_ENABLED" != "1" ]; then
        log "[FOLLOWUP] disabled，首轮 LLM 播放完成后直接退出对话"
        send_text_and_play "$session_id" "$first_text" normal
        led_off
        resume_native_asr
        CURRENT_SESSION_ID=""
        set_state "IDLE"
        return 0
    fi

    if [ "$FOLLOWUP_MODE" = "native_multirounds" ]; then
        log "[FOLLOWUP] mode=native_multirounds，不启动本地录音"
        last_dialog=$(get_aivs_lab_latest_dialog_id)
        native_followup_mark_multirounds
        send_text_and_play "$session_id" "$first_text" native_defer

        while true; do
            turn=$((turn + 1))
            set_state "FOLLOWUP_LISTENING"
            if ! wait_native_followup_text "$last_dialog" "$first_text"; then
                log "[FOLLOWUP] 原生追问 ASR 无文本，退出对话"
                break
            fi
            last_dialog=$(get_aivs_lab_latest_dialog_id)
            log "[TURN $turn] 原生追问转 LLM: $FOLLOWUP_TEXT"
            native_followup_mark_multirounds
            send_text_and_play "$session_id" "$FOLLOWUP_TEXT" native_defer
            log "[TURN $turn] 播放完成"
        done

        finish_llm_playback
        led_off
        resume_native_asr
        CURRENT_SESSION_ID=""
        set_state "IDLE"
        return 0
    fi

    send_text_and_play "$session_id" "$first_text" defer

    while true; do
        turn=$((turn + 1))
        wait_or_run_followup_vad
        ret=$?

        if [ "$ret" -eq 124 ]; then
            log "[TIMEOUT] ${FOLLOWUP_TIMEOUT}s 无语音，退出对话"
            break
        fi
        if [ "$ret" -ne 0 ]; then
            log "[FOLLOWUP] 录音失败，退出对话 ret=$ret"
            break
        fi

        if ! transcribe_followup_voice; then
            log "[FOLLOWUP] ASR 无文本，退出对话"
            break
        fi

        log "[TURN $turn] 发送追问到 LLM: $FOLLOWUP_TEXT"
        send_text_and_play "$session_id" "$FOLLOWUP_TEXT" defer
        log "[TURN $turn] 播放完成"
    done

    finish_llm_playback
    led_off
    resume_native_asr
    CURRENT_SESSION_ID=""
    set_state "IDLE"
}

handle_wakeup() {
    local wake_ts="$1"
    local session_id="native_first_${BACKEND}_$(date +%s)"
    local waited_ticks=0
    local max_ticks
    local wait_seconds
    local last_ts=0
    local fallback_query=""
    local saw_success=0
    local start_ms
    local elapsed
    local result_source

    log "[WAKE] native-first session=$session_id wake_ts=$wake_ts"
    NATIVE_FOLLOWUP_MARKED=0
    start_ms=$(monotonic_ms)
    result_source=$(select_native_result_source)
    log "[NATIVE] result source=$result_source"
    set_state "NATIVE_PROCESSING"
    led_on
    wait_seconds="$NATIVE_WAIT_SECONDS"
    if is_system1_root && [ "$result_source" = "aivs_lab_instruction" ]; then
        wait_seconds="$SYSTEM1_NATIVE_WAIT_SECONDS"
    fi
    max_ticks=$(awk -v s="$wait_seconds" -v p="$NATIVE_POLL_INTERVAL" 'BEGIN { printf "%d", (s / p) }')

    while [ "$waited_ticks" -lt "$max_ticks" ]; do
        sleep "$NATIVE_POLL_INTERVAL"
        get_native_result "$result_source" || true

        if [ -n "$RESULT_TS" ] && [ "$RESULT_TS" -ge "$wake_ts" ] && [ "$RESULT_TS" -gt "$last_ts" ] && [ -n "$RESULT_DOMAIN" ]; then
            last_ts="$RESULT_TS"
            [ -n "$RESULT_QUERY" ] && fallback_query="$RESULT_QUERY"
            elapsed=$(elapsed_s "$start_ms")
            log "[NATIVE] result source=$RESULT_SOURCE elapsed=${elapsed}s ticks=$waited_ticks interval=${NATIVE_POLL_INTERVAL}s ts=$RESULT_TS domain=$RESULT_DOMAIN action=$RESULT_ACTION query=$RESULT_QUERY speak=$RESULT_SPEAK"

            if is_ignored_query_result; then
                log "[NATIVE] ignored query result，忽略并回到待机"
                set_state "NATIVE_HANDLED"
                resume_native_player 1
                led_off
                set_state "IDLE"
                return 0
            fi

            if is_unsupported_result; then
                log "[NATIVE] unsupported，停止原生播报并转 LLM"
                set_state "NATIVE_FALLBACK"
                [ "$FOLLOWUP_ENABLED" = "1" ] && [ "$FOLLOWUP_MODE" = "native_multirounds" ] && native_followup_mark_multirounds
                freeze_native_player
                handle_llm_dialog "$session_id" "$fallback_query"
                return 0
            fi

            if is_native_success_domain; then
                log "[NATIVE] success-domain，交给小米原生"
                set_state "NATIVE_HANDLED"
                handle_native_success_speak
                led_off
                set_state "IDLE"
                return 0
            else
                log "[NATIVE] non-success-domain，立即 fallback LLM"
                set_state "NATIVE_FALLBACK"
                [ "$FOLLOWUP_ENABLED" = "1" ] && [ "$FOLLOWUP_MODE" = "native_multirounds" ] && native_followup_mark_multirounds
                freeze_native_player
                handle_llm_dialog "$session_id" "$fallback_query"
                return 0
            fi
        fi

        waited_ticks=$((waited_ticks + 1))
    done

    if [ "$saw_success" -eq 1 ]; then
        resume_native_player 0
        log "[NATIVE] handled by Xiaomi"
        led_off
        set_state "IDLE"
        return 0
    fi

    if [ -n "$fallback_query" ]; then
        log "[NATIVE] 无明确成功结果，fallback LLM query=$fallback_query"
        set_state "NATIVE_FALLBACK"
        [ "$FOLLOWUP_ENABLED" = "1" ] && [ "$FOLLOWUP_MODE" = "native_multirounds" ] && native_followup_mark_multirounds
        freeze_native_player
        handle_llm_dialog "$session_id" "$fallback_query"
        return 0
    fi

    resume_native_player 0
    led_off
    log "[NATIVE] ${wait_seconds}s 未拿到新结果，暂不 fallback"
    set_state "IDLE"
    return 1
}

cleanup() {
    led_off
    if [ -n "$HOOK_WATCHDOG_PID" ]; then
        kill "$HOOK_WATCHDOG_PID" 2>/dev/null
        HOOK_WATCHDOG_PID=""
    fi
    if [ -n "$FOLLOWUP_VAD_PID" ]; then
        kill "$FOLLOWUP_VAD_PID" 2>/dev/null
        FOLLOWUP_VAD_PID=""
    fi
    rm -f "$FOLLOWUP_ARM_FILE"
    rm -f "$NATIVE_REPLAY_CANCEL_MARKER"
    clear_busy
    resume_native_player
    restore_llm_master_volume
    restore_hook
    if ! should_setup_dsnoop; then
        restore_audio_capture_overlays
    fi
    resume_native_asr
    rm -f "$EVENT_FIFO" "$BUSY_MARKER"
    if [ -f "$PID_FILE" ] && [ "$(cat "$PID_FILE" 2>/dev/null)" = "$$" ]; then
        rm -f "$PID_FILE"
    fi
}

case "$1" in
    stop)
        stop_our_assistants
        cleanup
        exit 0
        ;;
    status)
        echo "--- mipns ---"
        ps | grep mipns | grep -v grep || true
        echo "--- hook ---"
        mount | grep ' /bin/wakeup.sh ' || true
        echo "--- client ---"
        ps | grep 'native_first_client.sh' | grep -v grep || true
        echo "--- logs ---"
        ls -l "$LOG_FILE" "$EVENT_LOG" 2>/dev/null || true
        exit 0
        ;;
    parse_test)
        source=$(select_native_result_source)
        get_native_result "$source" || true
        echo "source=$source"
        echo "result_source=$RESULT_SOURCE"
        echo "ts=$RESULT_TS"
        echo "domain=$RESULT_DOMAIN"
        echo "action=$RESULT_ACTION"
        echo "query=$RESULT_QUERY"
        echo "speak=$RESULT_SPEAK"
        exit 0
        ;;
esac

trap cleanup INT TERM EXIT

: > "$LOG_FILE"
exec >> "$LOG_FILE" 2>&1
echo "$$" > "$PID_FILE"

log "=== native-first + LLM fallback client ==="
apply_system_defaults
log "Config: $CONFIG_FILE"
log "Server: $SERVER"
log "Backend: $BACKEND"
log "LLM_VOLUME: $LLM_VOLUME"
log "LLM_MASTER_VOLUME: $LLM_MASTER_VOLUME"
log "LLM_MASTER_AUTO: media_scale=${LLM_MASTER_SCALE}% current_scale=${LLM_MASTER_CURRENT_SCALE}% min=$LLM_MASTER_MIN max=$LLM_MASTER_MAX"
log "Native result: source=${NATIVE_RESULT_SOURCE} selected=$(select_native_result_source) wait=${NATIVE_WAIT_SECONDS}s system1_wait=${SYSTEM1_NATIVE_WAIT_SECONDS}s interval=${NATIVE_POLL_INTERVAL}s ubus_timeout=${NATIVE_UBUS_TIMEOUT}s"
log "Wake event: max_age=${WAKE_EVENT_MAX_AGE}s"
log "Wake ignore queries: $WAKE_IGNORE_QUERIES"
log "Native success: domains=$NATIVE_SUCCESS_DOMAINS replay_speak=$NATIVE_REPLAY_SUCCESS_SPEAK replay_delay=${NATIVE_REPLAY_SUCCESS_DELAY}s replay_cancel_on_wake=$NATIVE_REPLAY_CANCEL_ON_WAKE cancel_domains=$NATIVE_REPLAY_CANCEL_DOMAINS grace=${NATIVE_REPLAY_CANCEL_GRACE}s window=${NATIVE_REPLAY_CANCEL_WINDOW}s"
log "Followup recorder: enabled=${FOLLOWUP_ENABLED} followup_mode=${FOLLOWUP_MODE} record_mode=${FOLLOWUP_RECORD_MODE} asr=${FOLLOWUP_ASR_ENGINE} native_min_bytes=${FOLLOWUP_NATIVE_MIN_QUERY_BYTES} native_poll=${NATIVE_FOLLOWUP_POLL_SECONDS}s/${NATIVE_FOLLOWUP_POLL_INTERVAL}s window=${FOLLOWUP_WINDOW_SECONDS}s capture=${FOLLOWUP_WINDOW_CAPTURE_DEV}/${FOLLOWUP_WINDOW_CAPTURE_FORMAT}/${FOLLOWUP_WINDOW_CAPTURE_RATE}/${FOLLOWUP_WINDOW_CAPTURE_CHANNELS}ch audio_setup=${AUDIO_CAPTURE_SETUP} root=$(root_device) window_gate=peak${FOLLOWUP_WINDOW_MIN_PEAK}/rms${FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD}/active${FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE}‰ timeout=${FOLLOWUP_TIMEOUT}s arm_delay=${FOLLOWUP_ARM_DELAY}s start=$FOLLOWUP_THRESHOLD/rms=$FOLLOWUP_START_RMS_THRESHOLD/active=${FOLLOWUP_START_ACTIVE_PERMILLE}‰ hits=$FOLLOWUP_START_HITS tail=${FOLLOWUP_IGNORE_INITIAL_CHUNKS}s/rms=$FOLLOWUP_TAIL_RMS_THRESHOLD/active=${FOLLOWUP_TAIL_ACTIVE_PERMILLE}‰ end=$FOLLOWUP_END_THRESHOLD/rms=$FOLLOWUP_END_RMS_THRESHOLD/active=${FOLLOWUP_END_ACTIVE_PERMILLE}‰ silence=${FOLLOWUP_SILENCE_LIMIT}s min_raw=$FOLLOWUP_MIN_RAW_BYTES prearm=$FOLLOWUP_PREARM"
log "Fallback: stop=${STOP_NATIVE_SECONDS}s freeze_mediaplayer=${FREEZE_NATIVE_PLAYER_ON_FALLBACK} prefreeze_on_think=${FREEZE_NATIVE_PLAYER_ON_THINK}"
log "Native ASR pause during LLM: $PAUSE_NATIVE_ASR_DURING_LLM"
log "Duplicate suppression: ${SUPPRESS_DUP_SECONDS}s"
init_native_result_state
set_state "INIT"

setup_audio
led_off
if should_setup_dsnoop; then
    setup_dsnoop
else
    restore_audio_capture_overlays
    log "[SETUP] 跳过 dsnoop/libxaudio 覆盖: AUDIO_CAPTURE_SETUP=$AUDIO_CAPTURE_SETUP root=$(root_device)"
fi
stop_our_assistants
: > "$EVENT_LOG"
mkfifo "$EVENT_FIFO" 2>/dev/null || mknod "$EVENT_FIFO" p 2>/dev/null

curl -s -o /dev/null -m 2 "$SERVER/" && log "服务器连接正常" || log "服务器无法连接"
set_state "IDLE"

install_hook
start_hook_watchdog
restart_mipns_single

log "[IDLE] 等待原生唤醒词：小爱同学"
exec 3<>"$EVENT_FIFO"
while true; do
    if ! read event ts <&3; then
        sleep 0.2
        continue
    fi

    case "$event" in
        WuW|think) ;;
        *) continue ;;
    esac
    now=$(date +%s)
    if [ -n "$ts" ] && [ $((now - ts)) -gt "$WAKE_EVENT_MAX_AGE" ] 2>/dev/null; then
        log "[WAKE] ignore stale event ts=$ts age=$((now - ts))s"
        continue
    fi
    if is_busy; then
        log "[WAKE] ignored while busy ts=$ts"
        continue
    fi
    handle_wakeup "$ts"
    log "[IDLE] 等待原生唤醒词：小爱同学"
done
