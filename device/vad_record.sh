#!/bin/sh
#
# VAD 录音模块 — 先录 S32_LE + S16_LE 检测静默
#

LAST_LOG_SEC=""
LAST_LOG_MS=0
LOG_TS=""

make_log_ts() {
    local base ms
    local sec
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

# 用法: sh vad_record.sh first [timeout]     # 首轮：默认一直等语音，传 timeout 后超时退出
#       sh vad_record.sh continue [timeout]  # 连续：10s 无语音超时
#
# 关键设计：先启动后台 S16_LE 单声道录音，再用 S16_LE chunk 检测，
# 确保语音不会被漏掉。

SPEECH_THRESHOLD="${SPEECH_THRESHOLD:-100}"  # 阶段1: 开始录音阈值
START_HITS="${START_HITS:-1}"                # 阶段1: 连续 N 个 chunk 超阈值才确认开始
END_THRESHOLD="${END_THRESHOLD:-100}"        # 阶段2: 结束录音阈值
SILENCE_LIMIT="${SILENCE_LIMIT:-3}"          # 连续静默 N 秒 = 结束
MAX_DURATION="${MAX_DURATION:-30}"
CONTINUE_TIMEOUT="${CONTINUE_TIMEOUT:-10}"
ARM_FILE="${VAD_ARM_FILE:-}"

MODE="${1:-first}"
TIMEOUT="${2:-$CONTINUE_TIMEOUT}"

TMP_DIR="/tmp/vad_chunks"
FINAL_WAV="/tmp/voice.wav"
CAPTURE_DEV="Capture"

LED_RGB="/sys/devices/i2c-1/1-003c/led_rgb"
LED_IDS="0 1 2 3 4 5 6 7 8 9 10 11"
LED_BLUE=16711680

led_set_all() {
    local color="$1"
    [ -w "$LED_RGB" ] || return 0
    LED_RGB_PATH="$LED_RGB" LED_IDS_LIST="$LED_IDS" LED_COLOR="$color" \
        timeout 2 sh -c 'for i in $LED_IDS_LIST; do echo "$i $LED_COLOR" > "$LED_RGB_PATH" 2>/dev/null; done' \
        >/dev/null 2>&1 &
}

led_on()  { led_set_all "$LED_BLUE"; }
led_off() { led_set_all 0; }

get_peak() {
    dd if="$1" bs=44 skip=1 2>/dev/null | \
        hexdump -v -e '1/2 "%d\n"' 2>/dev/null | \
        awk 'BEGIN{max=0} {v=$1;if(v<0)v=-v;if(v>max)max=v} END{print max+0}'
}

record_chunk() {
    arecord -D "$CAPTURE_DEV" -f S16_LE -r 16000 -c 1 -d 1 "$1" 2>/dev/null
}

# ─── 主流程 ───

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

log "[VAD] 模式=$MODE 开始阈值=$SPEECH_THRESHOLD 连续命中=${START_HITS} 结束阈值=$END_THRESHOLD 静默=${SILENCE_LIMIT}s"

if [ -n "$ARM_FILE" ]; then
    log "[VAD] 等待播放结束后再开始录音检测: $ARM_FILE"
    while [ ! -f "$ARM_FILE" ]; do
        sleep 0.1
    done
    log "[VAD] 播放结束，开始录音检测"
fi

# 立即启动后台 16kHz 单声道录音（确保不丢语音，同时显著降低上传和 ASR 成本）
arecord -D "$CAPTURE_DEV" -f S16_LE -r 16000 -c 1 \
    -d "$MAX_DURATION" "$FINAL_WAV" 2>/dev/null &
ARECORD_PID=$!

# ── 阶段 1: 等待语音 ──
speech_started=0
speech_hits=0
chunk_num=0
waited=0

if [ "$MODE" = "first" ]; then
    led_on
fi

while [ $speech_started -eq 0 ]; do
    chunk_file="$TMP_DIR/pre_$(printf '%04d' $chunk_num).wav"
    record_chunk "$chunk_file"

    peak=$(get_peak "$chunk_file" 2>/dev/null)
    rm -f "$chunk_file"
    chunk_num=$((chunk_num + 1))

    if [ $((chunk_num % 3)) -eq 0 ]; then
        log "[VAD] 等待语音... peak=$peak (${chunk_num}s)"
    fi

    if [ -n "$peak" ] && [ "$peak" -gt "$SPEECH_THRESHOLD" ]; then
        speech_hits=$((speech_hits + 1))
        if [ "$speech_hits" -lt "$START_HITS" ]; then
            log "[VAD] 疑似语音 ${speech_hits}/${START_HITS} (peak=$peak)"
        else
            speech_started=1
            log "[VAD] 检测到语音 (peak=$peak hits=$speech_hits)"
        fi
    else
        speech_hits=0
    fi

    if [ "$MODE" = "continue" ] || { [ "$MODE" = "first" ] && [ -n "$2" ]; }; then
        waited=$((waited + 1))
        if [ $waited -ge $TIMEOUT ]; then
            log "[VAD] ${TIMEOUT}s 无语音，超时退出"
            kill -INT $ARECORD_PID 2>/dev/null
            wait $ARECORD_PID 2>/dev/null
            rm -f "$FINAL_WAV"
            exit 124
        fi
    fi
done

if [ "$MODE" = "continue" ]; then
    led_on
fi

# ── 阶段 2: 检测静默结束 ──
log "[VAD] 录音中...（后台已录了 ${chunk_num}s）"
silence_count=0

while [ $silence_count -lt $SILENCE_LIMIT ]; do
    mon_file="$TMP_DIR/mon_$(printf '%04d' $silence_count).wav"
    record_chunk "$mon_file"

    peak=$(get_peak "$mon_file" 2>/dev/null)
    rm -f "$mon_file"

    if [ -n "$peak" ] && [ "$peak" -gt "$END_THRESHOLD" ]; then
        silence_count=0
        log "[VAD] 仍在说话... peak=$peak"
    else
        silence_count=$((silence_count + 1))
        if [ $silence_count -lt $SILENCE_LIMIT ]; then
            log "[VAD] 静默 ${silence_count}s..."
        fi
    fi
done

log "[VAD] 静默 ${SILENCE_LIMIT}s，停止录音"

# 停止后台录音
kill -INT $ARECORD_PID 2>/dev/null
wait $ARECORD_PID 2>/dev/null

# 不关 LED，由 wake_monitor 控制（对话中灯常亮）
rm -rf "$TMP_DIR"

if [ ! -f "$FINAL_WAV" ] || [ "$(wc -c < "$FINAL_WAV" 2>/dev/null)" -lt 1000 ]; then
    log "[VAD] 录音失败"
    exit 1
fi

log "[VAD] 录音完成: $FINAL_WAV ($(wc -c < "$FINAL_WAV") bytes)"
exit 0
