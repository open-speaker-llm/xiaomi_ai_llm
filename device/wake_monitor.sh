#!/bin/sh
#
# 对话状态机 Phase B — KWS 唤醒词 + 多 LLM 路由
#

SERVER="${SERVER:-http://192.168.8.150:8080}"
VAD_SCRIPT="/data/vad_record.sh"
BEEP="/tmp/beep.wav"
KWS_LOG="/tmp/kws_events.log"
KWS_DIR="${KWS_DIR:-/data/open-xiaoai/kws}"
KWS_THRESHOLD="${KWS_THRESHOLD:-0.03}"
KWS_SCORE="${KWS_SCORE:-2.0}"
FOLLOWUP_TIMEOUT="${FOLLOWUP_TIMEOUT:-6}"
FOLLOWUP_THRESHOLD="${FOLLOWUP_THRESHOLD:-220}"
FIRST_TURN_TIMEOUT="${FIRST_TURN_TIMEOUT:-8}"
STREAM_TIMEOUT="${STREAM_TIMEOUT:-180}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

LED_RGB="/sys/devices/i2c-1/1-003c/led_rgb"
LED_IDS="0 1 2 3 4 5 6 7 8 9 10 11"
LED_BLUE=16711680

led_set_all() {
    local color="$1"
    [ -w "$LED_RGB" ] || return 0
    for i in $LED_IDS; do
        echo "$i $color" > "$LED_RGB" 2>/dev/null
    done
}

led_on()  { led_set_all "$LED_BLUE"; }
led_off() { led_set_all 0; }

# LLM 路由表
route_backend() {
    case "$1" in
        "你好小智")     echo "minimax"   ;;
        "你好豆包")     echo "doubao"    ;;
        "你好deepseek") echo "deepseek"  ;;
        "你好深度")     echo "deepseek"  ;;
        "你好小深")     echo "deepseek"  ;;
        "小深同学")     echo "deepseek"  ;;
        "你好Kimi")     echo "kimi"      ;;
        *)              echo "minimax"   ;;
    esac
}

play_beep() {
    [ -f "$BEEP" ] && aplay "$BEEP" 2>/dev/null &
}

# 发送录音 + 流式播放
send_and_play() {
    local session_id="$1"; local backend="$2"
    local voice_file="/tmp/voice.wav"
    if [ ! -f "$voice_file" ]; then
        log "[ERROR] 录音文件不存在"
        return 1
    fi
    local size; size=$(wc -c < "$voice_file")
    log "[SEND] ${size} bytes → ${SERVER} (session=$session_id, backend=$backend)"

    rm -f /tmp/stream_fifo
    mkfifo /tmp/stream_fifo 2>/dev/null || mknod /tmp/stream_fifo p 2>/dev/null

    curl -s --no-buffer -o /tmp/stream_fifo --max-time "$STREAM_TIMEOUT" \
        -F "file=@${voice_file}" \
        "${SERVER}/api/v1/stream/chat?session_id=${session_id}&backend=${backend}&speed=1.0&volume=1.8" &
    CURL_PID=$!

    aplay /tmp/stream_fifo 2>/dev/null &
    APLAY_PID=$!

    wait $CURL_PID 2>/dev/null
    wait $APLAY_PID 2>/dev/null

    log "[SPEAKING] 播放完成..."
    sleep 1.5
    rm -f /tmp/stream_fifo
    return 0
}

# 启动 KWS（若未运行）
start_kws() {
    if [ ! -x "$KWS_DIR/kws" ] && [ -x /tmp/kws/kws ]; then
        KWS_DIR="/tmp/kws"
    fi
    if [ ! -x "$KWS_DIR/kws" ]; then
        log "[KWS] 二进制不存在: $KWS_DIR/kws"
        return 1
    fi

    # 杀掉旧 KWS 进程，确保从干净状态启动
    killall kws 2>/dev/null
    sleep 1
    log "[KWS] 启动唤醒词检测: $KWS_DIR threshold=$KWS_THRESHOLD score=$KWS_SCORE"
    :> "$KWS_LOG"  # 清空旧日志
    # stdout → 文件（不阻塞）, stderr → /dev/null
    "$KWS_DIR/kws" \
        --tokens="$KWS_DIR/models/tokens.txt" \
        --encoder="$KWS_DIR/models/encoder.onnx" \
        --decoder="$KWS_DIR/models/decoder.onnx" \
        --joiner="$KWS_DIR/models/joiner.onnx" \
        --keywords-file="$KWS_DIR/keywords.txt" \
        --model-type=zipformer2 \
        --provider=cpu --num-threads=1 --chunk-size=1024 \
        --keywords-threshold="$KWS_THRESHOLD" --keywords-score="$KWS_SCORE" \
        noop > "$KWS_LOG" 2>&1 &
    sleep 3
    if pidof kws > /dev/null 2>&1; then
        log "[KWS] 唤醒词检测已启动"
    else
        log "[KWS] 启动失败!"
        return 1
    fi
}

# ─── 主入口 ───
log "=== 对话状态机 Phase B (KWS) ==="
log "Server: $SERVER"

# 启动 KWS
start_kws || exit 1

# tail -f 监听日志，等待唤醒词
log "[IDLE] 等待唤醒词..."
tail -f "$KWS_LOG" 2>/dev/null | while read -r line; do
    # 兼容两种 KWS 输出:
    # 1) token token @你好小智
    # 2) 0:{"keyword": "你好小智", ...}
    keyword=""
    case "$line" in
        *@*)
            keyword=$(echo "$line" | cut -d'@' -f2)
            ;;
    esac
    if [ -z "$keyword" ]; then
        keyword=$(echo "$line" | tr -d '\r' | sed -n 's/.*"keyword"[ ]*:[ ]*"\([^"]*\)".*/\1/p')
    fi
    [ -n "$keyword" ] || continue

    backend=$(route_backend "$keyword")
    SESSION_ID="${backend}_$(date +%s)"

    log "[WAKING] 唤醒词=$keyword → backend=$backend session=$SESSION_ID"
    led_on

    # 唤醒后进入有限多轮。回答后只开放短追问窗口；超时即回到 IDLE。
    turn=1
    while true; do
        log ""
        if [ $turn -eq 1 ]; then
            log "[LISTEN] 请说话..."
            sh "$VAD_SCRIPT" first "$FIRST_TURN_TIMEOUT"
            ret=$?
            if [ $ret -eq 124 ]; then
                log "[TIMEOUT] 唤醒后 ${FIRST_TURN_TIMEOUT}s 无语音，退出对话"
                break
            fi
        else
            log "[FOLLOWUP] ${FOLLOWUP_TIMEOUT}s 内可继续追问..."
            SPEECH_THRESHOLD="$FOLLOWUP_THRESHOLD" sh "$VAD_SCRIPT" continue "$FOLLOWUP_TIMEOUT"
            ret=$?
            if [ $ret -eq 124 ]; then
                log "[TIMEOUT] ${FOLLOWUP_TIMEOUT}s 无语音，退出对话"
                break
            fi
        fi

        if [ $ret -ne 0 ]; then
            log "[LISTEN] 录音失败，退出对话 ret=$ret"
            break
        fi

        log "[TURN $turn] 发送到服务器..."
        send_and_play "$SESSION_ID" "$backend"
        log "[TURN $turn] 播放完成"

        turn=$((turn + 1))
    done
    led_off
    log "[IDLE] 等待唤醒词..."
done
