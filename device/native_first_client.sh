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
MIPNS_CONF="/usr/share/xiaomi/xaudio_engine.conf"
NATIVE_WAIT_SECONDS="${NATIVE_WAIT_SECONDS:-12}"
NATIVE_POLL_INTERVAL="${NATIVE_POLL_INTERVAL:-0.2}"
NATIVE_UBUS_TIMEOUT="${NATIVE_UBUS_TIMEOUT:-1}"
WAKE_EVENT_MAX_AGE="${WAKE_EVENT_MAX_AGE:-4}"
WAKE_IGNORE_QUERIES="${WAKE_IGNORE_QUERIES:-${WAKE_ONLY_QUERIES:-小爱同学 小爱 小爱小爱 小爱同学小爱同学 我在 在呢}}"
FOLLOWUP_TIMEOUT="${FOLLOWUP_TIMEOUT:-6}"
FOLLOWUP_THRESHOLD="${FOLLOWUP_THRESHOLD:-600}"
FOLLOWUP_START_HITS="${FOLLOWUP_START_HITS:-2}"
FOLLOWUP_END_THRESHOLD="${FOLLOWUP_END_THRESHOLD:-100}"
FOLLOWUP_SILENCE_LIMIT="${FOLLOWUP_SILENCE_LIMIT:-3}"
FOLLOWUP_PREARM="${FOLLOWUP_PREARM:-1}"
FOLLOWUP_PREARM_EXTRA="${FOLLOWUP_PREARM_EXTRA:-3}"
FOLLOWUP_ARM_DELAY="${FOLLOWUP_ARM_DELAY:-0.4}"
FOLLOWUP_ARM_FILE="/tmp/native_followup_vad.arm"
STREAM_TIMEOUT="${STREAM_TIMEOUT:-180}"
UNSUPPORTED_PATTERNS="${UNSUPPORTED_PATTERNS:-暂时|不会|不支持|回答不上|需要再学习|没听懂|不知道|不会这项技能}"
NATIVE_SUCCESS_DOMAINS="${NATIVE_SUCCESS_DOMAINS:-smartMiot soundboxControl time weather music player alarm timer system volume}"
NATIVE_REPLAY_SUCCESS_SPEAK="${NATIVE_REPLAY_SUCCESS_SPEAK:-1}"
NATIVE_REPLAY_SUCCESS_DELAY="${NATIVE_REPLAY_SUCCESS_DELAY:-0}"
STOP_NATIVE_SECONDS="${STOP_NATIVE_SECONDS:-15}"
SUPPRESS_DUP_SECONDS="${SUPPRESS_DUP_SECONDS:-0}"
FREEZE_NATIVE_PLAYER_ON_FALLBACK="${FREEZE_NATIVE_PLAYER_ON_FALLBACK:-1}"
FREEZE_NATIVE_PLAYER_ON_THINK="${FREEZE_NATIVE_PLAYER_ON_THINK:-1}"
MASTER_RESTORE_VALUE=""
LLM_SESSION_MASTER_TARGET=""
FOLLOWUP_VAD_PID=""
HOOK_WATCHDOG_PID=""
CURRENT_SESSION_ID=""
NATIVE_PLAYER_FROZEN=0
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

    killall mipns-xiaomi 2>/dev/null
    sleep 1
    /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" >/tmp/native_mipns.log 2>&1 &
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
    if [ -f "$ORIG_WAKEUP" ] && grep -q 'play_wakeup' "$ORIG_WAKEUP" 2>/dev/null; then
        return 0
    fi
    cp /bin/wakeup.sh "$ORIG_WAKEUP"
}

install_hook() {
    restore_hook
    ensure_original_wakeup

    cat > "$HOOK_WAKEUP" << 'EOF'
#!/bin/sh
CONFIG_FILE="${CONFIG_FILE:-/data/native_first.env}"
[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"
EVENT_FIFO="${EVENT_FIFO:-/tmp/native_first_event.fifo}"
EVENT_LOG="${EVENT_LOG:-/tmp/native_first_events.log}"
ORIG_WAKEUP="${ORIG_WAKEUP:-/tmp/wakeup.sh.orig}"
PLAYER_FROZEN_MARKER="${PLAYER_FROZEN_MARKER:-/tmp/native_first_player_frozen}"
BUSY_MARKER="${BUSY_MARKER:-/tmp/native_first_busy}"
FREEZE_NATIVE_PLAYER_ON_THINK="${FREEZE_NATIVE_PLAYER_ON_THINK:-1}"

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
        if [ -f "$BUSY_MARKER" ]; then
            echo "[$(log_ts)] NATIVE_WAKE_IGNORED_BUSY args=$* ts=$ts" >> "$EVENT_LOG"
        elif [ -p "$EVENT_FIFO" ]; then
            ( echo "WuW $ts" > "$EVENT_FIFO" 2>/dev/null ) &
        fi
        ;;
    think)
        echo "[$(log_ts)] NATIVE_WAKE_EVENT args=$*" >> "$EVENT_LOG"
        if [ -f "$BUSY_MARKER" ]; then
            echo "[$(log_ts)] NATIVE_THINK_IGNORED_BUSY args=$*" >> "$EVENT_LOG"
        elif [ "$FREEZE_NATIVE_PLAYER_ON_THINK" = "1" ]; then
            killall -STOP mediaplayer 2>/dev/null
            date +%s > "$PLAYER_FROZEN_MARKER"
            echo "[$(log_ts)] NATIVE_PRE_FREEZE args=$*" >> "$EVENT_LOG"
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
    if pidof mipns-xiaomi >/dev/null 2>&1; then
        killall -CONT mipns-xiaomi 2>/dev/null
    else
        /usr/bin/mipns-xiaomi -c "$MIPNS_CONF" >/tmp/native_mipns.log 2>&1 &
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

get_latest_native_result() {
    local raw="$1"
    local item

    RESULT_TS=""
    RESULT_DOMAIN=""
    RESULT_ACTION=""
    RESULT_QUERY=""
    RESULT_SPEAK=""

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

handle_native_success_speak() {
    if [ -z "$RESULT_SPEAK" ]; then
        resume_native_player 0
        return 0
    fi

    case "$NATIVE_REPLAY_SUCCESS_SPEAK" in
        1|yes|true)
            resume_native_player 0
            native_tts_speak "$RESULT_SPEAK"
            ;;
        auto)
            resume_native_player 0
            log "[NATIVE] success speak auto replay after ${NATIVE_REPLAY_SUCCESS_DELAY}s"
            sleep "$NATIVE_REPLAY_SUCCESS_DELAY"
            native_tts_speak "$RESULT_SPEAK"
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
    killall -STOP mipns-xiaomi 2>/dev/null
    log "[NATIVE] mipns paused for LLM followup"
}

resume_native_asr() {
    killall -CONT mipns-xiaomi 2>/dev/null
    log "[NATIVE] mipns resumed"
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

    timeout="$FOLLOWUP_TIMEOUT"
    rm -f "$FOLLOWUP_ARM_FILE"
    log "[FOLLOWUP] prearm VAD: wait_playback_done timeout=${timeout}s start=$FOLLOWUP_THRESHOLD end=$FOLLOWUP_END_THRESHOLD silence=${FOLLOWUP_SILENCE_LIMIT}s"
    (
        VAD_ARM_FILE="$FOLLOWUP_ARM_FILE" \
        SPEECH_THRESHOLD="$FOLLOWUP_THRESHOLD" \
        START_HITS="$FOLLOWUP_START_HITS" \
        END_THRESHOLD="$FOLLOWUP_END_THRESHOLD" \
        SILENCE_LIMIT="$FOLLOWUP_SILENCE_LIMIT" \
        sh "$VAD_SCRIPT" continue "$timeout"
    ) &
    FOLLOWUP_VAD_PID=$!
}

arm_followup_vad() {
    if [ -n "$FOLLOWUP_VAD_PID" ]; then
        log "[FOLLOWUP] wait ${FOLLOWUP_ARM_DELAY}s for speaker tail"
        sleep "$FOLLOWUP_ARM_DELAY"
        touch "$FOLLOWUP_ARM_FILE" 2>/dev/null
        log "[FOLLOWUP] arm VAD after playback"
    fi
}

wait_or_run_followup_vad() {
    local ret

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
    log "[FOLLOWUP] ${FOLLOWUP_TIMEOUT}s 内可继续追问..."
    SPEECH_THRESHOLD="$FOLLOWUP_THRESHOLD" \
    START_HITS="$FOLLOWUP_START_HITS" \
    END_THRESHOLD="$FOLLOWUP_END_THRESHOLD" \
    SILENCE_LIMIT="$FOLLOWUP_SILENCE_LIMIT" \
    sh "$VAD_SCRIPT" continue "$FOLLOWUP_TIMEOUT"
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

    wait $CURL_PID 2>/dev/null
    t1=$(date +%s)
    log "[LLM] stream download done in $((t1 - t0))s"
    if [ "$cleanup_mode" = "defer" ]; then
        start_followup_vad_prearm
    fi
    wait $APLAY_PID 2>/dev/null
    t2=$(date +%s)
    log "[LLM] aplay done in $((t2 - t0))s (drain=$((t2 - t1))s)"
    if [ "$cleanup_mode" = "defer" ]; then
        arm_followup_vad
    fi
    if [ "$cleanup_mode" = "defer" ]; then
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

transcribe_followup_voice() {
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

handle_llm_dialog() {
    local session_id="$1"
    local first_text="$2"
    local turn=1
    local ret

    CURRENT_SESSION_ID="$session_id"
    set_state "LLM_DIALOG"
    led_on
    pause_native_asr
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
    local last_ts=0
    local fallback_query=""
    local saw_success=0
    local start_ms
    local elapsed

    log "[WAKE] native-first session=$session_id wake_ts=$wake_ts"
    start_ms=$(monotonic_ms)
    set_state "NATIVE_PROCESSING"
    led_on
    max_ticks=$(awk -v s="$NATIVE_WAIT_SECONDS" -v p="$NATIVE_POLL_INTERVAL" 'BEGIN { printf "%d", (s / p) }')

    while [ "$waited_ticks" -lt "$max_ticks" ]; do
        sleep "$NATIVE_POLL_INTERVAL"
        raw=$(ubus -t "$NATIVE_UBUS_TIMEOUT" call mibrain nlp_result_get)
        get_latest_native_result "$raw"

        if [ -n "$RESULT_TS" ] && [ "$RESULT_TS" -ge "$wake_ts" ] && [ "$RESULT_TS" -gt "$last_ts" ] && [ -n "$RESULT_DOMAIN" ]; then
            last_ts="$RESULT_TS"
            [ -n "$RESULT_QUERY" ] && fallback_query="$RESULT_QUERY"
            elapsed=$(elapsed_s "$start_ms")
            log "[NATIVE] result elapsed=${elapsed}s ticks=$waited_ticks interval=${NATIVE_POLL_INTERVAL}s ts=$RESULT_TS domain=$RESULT_DOMAIN action=$RESULT_ACTION query=$RESULT_QUERY speak=$RESULT_SPEAK"

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
        freeze_native_player
        handle_llm_dialog "$session_id" "$fallback_query"
        return 0
    fi

    resume_native_player 0
    led_off
    log "[NATIVE] ${NATIVE_WAIT_SECONDS}s 未拿到新结果，暂不 fallback"
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
    clear_busy
    resume_native_player
    restore_llm_master_volume
    restore_hook
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
        raw=$(ubus -t 2 call mibrain nlp_result_get)
        get_latest_native_result "$raw"
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
log "Config: $CONFIG_FILE"
log "Server: $SERVER"
log "Backend: $BACKEND"
log "LLM_VOLUME: $LLM_VOLUME"
log "LLM_MASTER_VOLUME: $LLM_MASTER_VOLUME"
log "LLM_MASTER_AUTO: media_scale=${LLM_MASTER_SCALE}% current_scale=${LLM_MASTER_CURRENT_SCALE}% min=$LLM_MASTER_MIN max=$LLM_MASTER_MAX"
log "Native poll: interval=${NATIVE_POLL_INTERVAL}s ubus_timeout=${NATIVE_UBUS_TIMEOUT}s wait=${NATIVE_WAIT_SECONDS}s"
log "Wake event: max_age=${WAKE_EVENT_MAX_AGE}s"
log "Wake ignore queries: $WAKE_IGNORE_QUERIES"
log "Native success: domains=$NATIVE_SUCCESS_DOMAINS replay_speak=$NATIVE_REPLAY_SUCCESS_SPEAK replay_delay=${NATIVE_REPLAY_SUCCESS_DELAY}s"
log "Followup VAD: timeout=${FOLLOWUP_TIMEOUT}s arm_delay=${FOLLOWUP_ARM_DELAY}s start=$FOLLOWUP_THRESHOLD hits=$FOLLOWUP_START_HITS end=$FOLLOWUP_END_THRESHOLD silence=${FOLLOWUP_SILENCE_LIMIT}s prearm=$FOLLOWUP_PREARM"
log "Fallback: stop=${STOP_NATIVE_SECONDS}s freeze_mediaplayer=${FREEZE_NATIVE_PLAYER_ON_FALLBACK} prefreeze_on_think=${FREEZE_NATIVE_PLAYER_ON_THINK}"
log "Duplicate suppression: ${SUPPRESS_DUP_SECONDS}s"
set_state "INIT"

setup_audio
led_off
setup_dsnoop
stop_our_assistants
: > "$EVENT_LOG"
mkfifo "$EVENT_FIFO" 2>/dev/null || mknod "$EVENT_FIFO" p 2>/dev/null

curl -s -o /dev/null -m 2 "$SERVER/" && log "服务器连接正常" || log "服务器无法连接"
set_state "IDLE"

install_hook
start_hook_watchdog
start_mipns

log "[IDLE] 等待原生唤醒词：小爱同学"
exec 3<>"$EVENT_FIFO"
while true; do
    if ! read event ts <&3; then
        sleep 0.2
        continue
    fi

    [ "$event" = "WuW" ] || continue
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
