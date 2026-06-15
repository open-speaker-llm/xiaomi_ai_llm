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
#       sh vad_record.sh continue [timeout]  # 连续：VAD 判断语音起止
#       sh vad_record.sh window [seconds]    # 固定窗口录音，用服务端 ASR 判断是否有人声
#
# 关键设计：先启动后台 S16_LE 单声道录音，再用 S16_LE chunk 检测，
# 确保语音不会被漏掉。

SPEECH_THRESHOLD="${SPEECH_THRESHOLD:-100}"  # 阶段1: 开始录音阈值
START_HITS="${START_HITS:-1}"                # 阶段1: 连续 N 个 chunk 超阈值才确认开始
END_THRESHOLD="${END_THRESHOLD:-100}"        # 阶段2: 结束录音阈值
START_RMS_THRESHOLD="${START_RMS_THRESHOLD:-0}"
END_RMS_THRESHOLD="${END_RMS_THRESHOLD:-0}"
START_ACTIVE_PERMILLE="${START_ACTIVE_PERMILLE:-0}"
END_ACTIVE_PERMILLE="${END_ACTIVE_PERMILLE:-0}"
IGNORE_INITIAL_CHUNKS="${IGNORE_INITIAL_CHUNKS:-0}"
TAIL_RMS_THRESHOLD="${TAIL_RMS_THRESHOLD:-$START_RMS_THRESHOLD}"
TAIL_ACTIVE_PERMILLE="${TAIL_ACTIVE_PERMILLE:-$START_ACTIVE_PERMILLE}"
SILENCE_LIMIT="${SILENCE_LIMIT:-3}"          # 连续静默 N 秒 = 结束
MAX_DURATION="${MAX_DURATION:-30}"
CONTINUE_TIMEOUT="${CONTINUE_TIMEOUT:-10}"
ARM_FILE="${VAD_ARM_FILE:-}"
ARM_POLL_SECONDS="${ARM_POLL_SECONDS:-0.03}"
MIN_RAW_BYTES="${MIN_RAW_BYTES:-16000}"       # 16kHz/16bit/mono 下约 0.5 秒
WINDOW_CAPTURE_DEV="${WINDOW_CAPTURE_DEV:-$CAPTURE_DEV}"
WINDOW_CAPTURE_FORMAT="${WINDOW_CAPTURE_FORMAT:-S16_LE}"
WINDOW_CAPTURE_RATE="${WINDOW_CAPTURE_RATE:-16000}"
WINDOW_CAPTURE_CHANNELS="${WINDOW_CAPTURE_CHANNELS:-1}"
WINDOW_MIN_PEAK="${WINDOW_MIN_PEAK:-300}"
WINDOW_MIN_RMS_THRESHOLD="${WINDOW_MIN_RMS_THRESHOLD:-40}"
WINDOW_MIN_ACTIVE_PERMILLE="${WINDOW_MIN_ACTIVE_PERMILLE:-5}"

MODE="${1:-first}"
TIMEOUT="${2:-$CONTINUE_TIMEOUT}"

TMP_DIR="/tmp/vad_chunks"
FINAL_WAV="/tmp/voice.wav"
RAW_PCM="$TMP_DIR/voice.raw"
HIT_DIR="$TMP_DIR/hits"
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

get_audio_stats() {
    dd if="$1" bs=44 skip=1 2>/dev/null | \
        hexdump -v -e '1/2 "%d\n"' 2>/dev/null | \
        awk -v active_thr="$ACTIVE_THRESHOLD" '
            BEGIN { max=0; sumsq=0; n=0; active=0 }
            {
                v=$1
                if (v < 0) v=-v
                if (v > max) max=v
                sumsq += v * v
                n += 1
                if (active_thr > 0 && v > active_thr) active += 1
            }
            END {
                rms = n > 0 ? sqrt(sumsq / n) : 0
                active_permille = (n > 0 && active_thr > 0) ? int(active * 1000 / n) : 1000
                printf "%d %d %d\n", max + 0, rms + 0.5, active_permille
            }'
}

record_chunk() {
    arecord -D "$CAPTURE_DEV" -f S16_LE -r 16000 -c 1 -d 1 "$1" 2>/dev/null
}

append_pcm() {
    dd if="$1" bs=44 skip=1 2>/dev/null >> "$RAW_PCM"
}

write_wav_header() {
    local out="$1"
    local data_bytes="$2"

    putb() {
        printf "\\$(printf "%03o" "$1")"
    }
    le16() {
        local n="$1"
        putb $((n % 256))
        putb $(((n / 256) % 256))
    }
    le32() {
        local n="$1"
        putb $((n % 256))
        putb $(((n / 256) % 256))
        putb $(((n / 65536) % 256))
        putb $(((n / 16777216) % 256))
    }

    {
        printf "RIFF"
        le32 $((data_bytes + 36))
        printf "WAVE"
        printf "fmt "
        le32 16
        le16 1
        le16 1
        le32 16000
        le32 32000
        le16 2
        le16 16
        printf "data"
        le32 "$data_bytes"
    } > "$out"
}

finalize_wav() {
    local data_bytes
    data_bytes=$(wc -c < "$RAW_PCM" 2>/dev/null)
    data_bytes="${data_bytes:-0}"
    if [ "$data_bytes" -lt "$MIN_RAW_BYTES" ]; then
        return 1
    fi
    write_wav_header "$FINAL_WAV" "$data_bytes"
    cat "$RAW_PCM" >> "$FINAL_WAV"
}

# ─── 主流程 ───

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
mkdir -p "$HIT_DIR"
rm -f "$FINAL_WAV" "$RAW_PCM"

log "[VAD] 模式=$MODE 开始阈值=$SPEECH_THRESHOLD rms=$START_RMS_THRESHOLD active=${START_ACTIVE_PERMILLE}‰ 连续命中=${START_HITS} 候选开头=${IGNORE_INITIAL_CHUNKS}s tail_rms=$TAIL_RMS_THRESHOLD tail_active=${TAIL_ACTIVE_PERMILLE}‰ 结束阈值=$END_THRESHOLD rms=$END_RMS_THRESHOLD active=${END_ACTIVE_PERMILLE}‰ 静默=${SILENCE_LIMIT}s"

if [ -n "$ARM_FILE" ]; then
    log "[VAD] 等待播放结束后再开始录音检测: $ARM_FILE poll=${ARM_POLL_SECONDS}s"
    while [ ! -f "$ARM_FILE" ]; do
        sleep "$ARM_POLL_SECONDS"
    done
    log "[VAD] 播放结束，开始录音检测"
fi

if [ "$MODE" = "stream" ]; then
    # 连续后台录音(无块间空档) + 轮询文件尾部 RMS：等你开口才算起、检测到说完静默就停，
    # 并有最长上限。解决 window 盲录满 8s 要傻等、且最长只 8s 的问题。
    POLL_CS=30                                    # 轮询 0.3s（厘秒）
    TAIL_BYTES=12800                              # 尾部 ~0.4s @16k/16bit
    sil_to=$(( SILENCE_LIMIT * 100 / POLL_CS ))   # 说完静默（迭代数）
    max_to=$(( MAX_DURATION * 100 / POLL_CS ))    # 最长语音（迭代数）
    # 预热：跳过录音启动瞬间的 ALSA 冷启动爆音 + TTS 残响，期间只录音不判起。
    warmup_it=$(( IGNORE_INITIAL_CHUNKS * 100 / POLL_CS ))
    [ "$warmup_it" -lt 4 ] && warmup_it=4         # 至少 ~1.2s
    onset_to=$(( warmup_it + TIMEOUT * 100 / POLL_CS ))  # 等开口超时（预热之后再给 TIMEOUT 秒）
    hard=$(( TIMEOUT + MAX_DURATION + 4 ))        # arecord 硬上限（兜底）
    cap="$TMP_DIR/cap.wav"
    log "[VAD] 流式录音 dev=$WINDOW_CAPTURE_DEV 预热=$((warmup_it*POLL_CS/100))s 等开口=${TIMEOUT}s 最长=${MAX_DURATION}s start_rms=$START_RMS_THRESHOLD end_rms=$END_RMS_THRESHOLD 静默=${SILENCE_LIMIT}s"
    arecord -D "$WINDOW_CAPTURE_DEV" -f S16_LE -r "$WINDOW_CAPTURE_RATE" -c 1 -d "$hard" "$cap" 2>/dev/null &
    AREC_PID=$!
    it=0; sil=0; onset_it=0; started=0; onset_hits=0
    while kill -0 "$AREC_PID" 2>/dev/null; do
        sleep 0.3
        it=$((it + 1))
        [ -f "$cap" ] || continue
        rms=$(tail -c "$TAIL_BYTES" "$cap" 2>/dev/null | hexdump -v -e '1/2 "%d\n"' 2>/dev/null \
            | awk '{ v=$1; if (v<0) v=-v; s+=v*v; n++ } END { print (n>0)? int(sqrt(s/n)) : 0 }')
        rms="${rms:-0}"
        if [ "$started" -eq 0 ]; then
            if [ "$it" -gt "$warmup_it" ] && [ "$rms" -ge "$START_RMS_THRESHOLD" ]; then
                onset_hits=$((onset_hits + 1))                # 要求连续 2 次，滤掉单次尖峰/爆音
                if [ "$onset_hits" -ge 2 ]; then
                    started=1; onset_it=$it
                    log "[VAD] 检测到语音开始 rms=$rms"
                fi
            else
                onset_hits=0
                if [ "$it" -ge "$onset_to" ]; then
                    log "[VAD] ${TIMEOUT}s 无语音，超时退出"
                    kill "$AREC_PID" 2>/dev/null; wait "$AREC_PID" 2>/dev/null
                    rm -rf "$TMP_DIR"; rm -f "$FINAL_WAV"; exit 124
                fi
            fi
        else
            if [ "$rms" -lt "$END_RMS_THRESHOLD" ]; then
                sil=$((sil + 1))
                if [ "$sil" -ge "$sil_to" ]; then
                    log "[VAD] 说完(静默${SILENCE_LIMIT}s)，停止录音 rms=$rms"
                    break
                fi
            else
                sil=0
            fi
            if [ $((it - onset_it)) -ge "$max_to" ]; then
                log "[VAD] 达最长 ${MAX_DURATION}s，停止录音"
                break
            fi
        fi
    done
    kill "$AREC_PID" 2>/dev/null; wait "$AREC_PID" 2>/dev/null
    if [ ! -f "$cap" ]; then
        log "[VAD] 流式录音失败"; rm -rf "$TMP_DIR"; rm -f "$FINAL_WAV"; exit 1
    fi
    dd if="$cap" bs=44 skip=1 2>/dev/null > "$RAW_PCM"
    data_bytes=$(wc -c < "$RAW_PCM" 2>/dev/null); data_bytes="${data_bytes:-0}"
    if [ "$data_bytes" -lt "$MIN_RAW_BYTES" ]; then
        log "[VAD] 流式录音过短 ${data_bytes}B，退出"
        rm -rf "$TMP_DIR"; rm -f "$FINAL_WAV"; exit 124
    fi
    write_wav_header "$FINAL_WAV" "$data_bytes"
    cat "$RAW_PCM" >> "$FINAL_WAV"
    rm -rf "$TMP_DIR"
    log "[VAD] 录音完成: $FINAL_WAV ($(wc -c < "$FINAL_WAV") bytes)"
    exit 0
fi

if [ "$MODE" = "window" ]; then
    # S32 采集 + micnorm 归一化：解决安静追问被 S16 直采砍到 ~8bit、云端识别不了的问题。
    # 仅在 micnorm 可用且目标为 S16/1ch（追问场景）时启用；否则回退老 S16 直采。
    MICNORM="${MICNORM_BIN:-/data/micnorm}"
    if [ -x "$MICNORM" ] && [ "$WINDOW_CAPTURE_FORMAT" = "S16_LE" ] && [ "$WINDOW_CAPTURE_CHANNELS" = "1" ]; then
        cap="$TMP_DIR/cap_s32.wav"
        log "[VAD] 固定窗口录音(S32+归一化) ${TIMEOUT}s dev=$WINDOW_CAPTURE_DEV rate=$WINDOW_CAPTURE_RATE..."
        arecord -D "$WINDOW_CAPTURE_DEV" -f S32_LE -r "$WINDOW_CAPTURE_RATE" -c 1 -d "$TIMEOUT" "$cap" 2>/dev/null
        if [ ! -f "$cap" ] || [ "$(wc -c < "$cap" 2>/dev/null)" -lt 1000 ]; then
            log "[VAD] 录音失败"; rm -rf "$TMP_DIR"; exit 1
        fi
        "$MICNORM" "$cap" "$FINAL_WAV" "${MICNORM_TARGET_PEAK:-18000}" "${MICNORM_MIN_PEAK:-1200000}" "${MICNORM_MAX_BOOST:-1}" 2>&1
        ret=$?
        rm -rf "$TMP_DIR"
        if [ "$ret" = "124" ]; then
            log "[VAD] 窗口无有效语音(micnorm)，超时退出"; rm -f "$FINAL_WAV"; exit 124
        fi
        if [ "$ret" != "0" ] || [ ! -s "$FINAL_WAV" ]; then
            log "[VAD] micnorm 失败 ret=$ret，本轮放弃"; rm -f "$FINAL_WAV"; exit 1
        fi
        log "[VAD] 录音完成: $FINAL_WAV ($(wc -c < "$FINAL_WAV") bytes)"
        exit 0
    fi

    log "[VAD] 固定窗口录音 ${TIMEOUT}s dev=$WINDOW_CAPTURE_DEV format=$WINDOW_CAPTURE_FORMAT rate=$WINDOW_CAPTURE_RATE channels=$WINDOW_CAPTURE_CHANNELS..."
    arecord -D "$WINDOW_CAPTURE_DEV" \
        -f "$WINDOW_CAPTURE_FORMAT" \
        -r "$WINDOW_CAPTURE_RATE" \
        -c "$WINDOW_CAPTURE_CHANNELS" \
        -d "$TIMEOUT" \
        "$FINAL_WAV" 2>/dev/null

    if [ ! -f "$FINAL_WAV" ] || [ "$(wc -c < "$FINAL_WAV" 2>/dev/null)" -lt 1000 ]; then
        log "[VAD] 录音失败"
        rm -rf "$TMP_DIR"
        exit 1
    fi

    if [ "$WINDOW_CAPTURE_FORMAT" = "S16_LE" ] && [ "$WINDOW_CAPTURE_CHANNELS" = "1" ]; then
        ACTIVE_THRESHOLD="$WINDOW_MIN_PEAK"
        stats=$(get_audio_stats "$FINAL_WAV" 2>/dev/null)
        peak=$(echo "$stats" | awk '{print $1}')
        rms=$(echo "$stats" | awk '{print $2}')
        active_permille=$(echo "$stats" | awk '{print $3}')
        log "[VAD] 窗口统计 peak=${peak:-0} rms=${rms:-0} active=${active_permille:-0}‰"
        if [ "${peak:-0}" -lt "$WINDOW_MIN_PEAK" ] \
            && [ "${rms:-0}" -lt "$WINDOW_MIN_RMS_THRESHOLD" ] \
            && [ "${active_permille:-0}" -lt "$WINDOW_MIN_ACTIVE_PERMILLE" ]; then
            log "[VAD] 窗口无有效语音，超时退出"
            rm -rf "$TMP_DIR"
            rm -f "$FINAL_WAV"
            exit 124
        fi
    fi

    rm -rf "$TMP_DIR"
    log "[VAD] 录音完成: $FINAL_WAV ($(wc -c < "$FINAL_WAV") bytes)"
    exit 0
fi

# ── 阶段 1: 等待语音 ──
speech_started=0
speech_hits=0
chunk_num=0
waited=0
recorded_chunks=0
tail_candidate=0

if [ "$MODE" = "first" ]; then
    led_on
fi

while [ $speech_started -eq 0 ]; do
    chunk_file="$TMP_DIR/pre_$(printf '%04d' $chunk_num).wav"
    record_chunk "$chunk_file"

    ACTIVE_THRESHOLD="$SPEECH_THRESHOLD"
    stats=$(get_audio_stats "$chunk_file" 2>/dev/null)
    peak=$(echo "$stats" | awk '{print $1}')
    rms=$(echo "$stats" | awk '{print $2}')
    active_permille=$(echo "$stats" | awk '{print $3}')
    chunk_num=$((chunk_num + 1))

    if [ $((chunk_num % 3)) -eq 0 ]; then
        log "[VAD] 等待语音... peak=$peak rms=$rms active=${active_permille}‰ (${chunk_num}s)"
    fi

    if [ "$chunk_num" -le "$IGNORE_INITIAL_CHUNKS" ]; then
        if [ -n "$peak" ] && [ "$peak" -gt "$SPEECH_THRESHOLD" ] \
            && [ "${rms:-0}" -ge "$TAIL_RMS_THRESHOLD" ] \
            && [ "${active_permille:-0}" -ge "$TAIL_ACTIVE_PERMILLE" ]; then
            tail_candidate=1
            cp "$chunk_file" "$HIT_DIR/tail_$(printf '%04d' "$chunk_num").wav" 2>/dev/null
            log "[VAD] 早说话候选 ${chunk_num}/${IGNORE_INITIAL_CHUNKS} (peak=$peak rms=$rms active=${active_permille}‰)"
        else
            log "[VAD] 忽略播放尾音窗口 ${chunk_num}/${IGNORE_INITIAL_CHUNKS} (peak=$peak rms=$rms active=${active_permille}‰)"
        fi
        rm -f "$chunk_file"
        if [ "$MODE" = "continue" ] || { [ "$MODE" = "first" ] && [ -n "$2" ]; }; then
            waited=$((waited + 1))
            if [ $waited -ge $TIMEOUT ]; then
                log "[VAD] ${TIMEOUT}s 无语音，超时退出"
                rm -f "$FINAL_WAV"
                exit 124
            fi
        fi
        continue
    fi

    if [ -n "$peak" ] && [ "$peak" -gt "$SPEECH_THRESHOLD" ] \
        && [ "${rms:-0}" -ge "$START_RMS_THRESHOLD" ] \
        && [ "${active_permille:-0}" -ge "$START_ACTIVE_PERMILLE" ]; then
        speech_hits=$((speech_hits + 1))
        cp "$chunk_file" "$HIT_DIR/hit_$(printf '%04d' "$speech_hits").wav" 2>/dev/null
        if [ "$speech_hits" -lt "$START_HITS" ]; then
            log "[VAD] 疑似语音 ${speech_hits}/${START_HITS} (peak=$peak rms=$rms active=${active_permille}‰)"
        else
            speech_started=1
            log "[VAD] 检测到语音 (peak=$peak rms=$rms active=${active_permille}‰ hits=$speech_hits)"
            for hit_file in "$HIT_DIR"/tail_*.wav "$HIT_DIR"/hit_*.wav; do
                [ -f "$hit_file" ] || continue
                append_pcm "$hit_file"
                recorded_chunks=$((recorded_chunks + 1))
            done
        fi
    else
        speech_hits=0
        rm -f "$HIT_DIR"/hit_[0-9]*.wav
    fi
    rm -f "$chunk_file"

    if [ "$MODE" = "continue" ] || { [ "$MODE" = "first" ] && [ -n "$2" ]; }; then
        waited=$((waited + 1))
        if [ $waited -ge $TIMEOUT ]; then
            if [ "$tail_candidate" -eq 1 ]; then
                log "[VAD] 超时前仅检测到早说话候选，提交 ASR 判定"
                for hit_file in "$HIT_DIR"/tail_*.wav; do
                    [ -f "$hit_file" ] || continue
                    append_pcm "$hit_file"
                    recorded_chunks=$((recorded_chunks + 1))
                done
                speech_started=1
                break
            fi
            log "[VAD] ${TIMEOUT}s 无语音，超时退出"
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

    ACTIVE_THRESHOLD="$END_THRESHOLD"
    stats=$(get_audio_stats "$mon_file" 2>/dev/null)
    peak=$(echo "$stats" | awk '{print $1}')
    rms=$(echo "$stats" | awk '{print $2}')
    active_permille=$(echo "$stats" | awk '{print $3}')
    append_pcm "$mon_file"
    recorded_chunks=$((recorded_chunks + 1))
    rm -f "$mon_file"

    if [ -n "$peak" ] && [ "$peak" -gt "$END_THRESHOLD" ] \
        && [ "${rms:-0}" -ge "$END_RMS_THRESHOLD" ] \
        && [ "${active_permille:-0}" -ge "$END_ACTIVE_PERMILLE" ]; then
        silence_count=0
        log "[VAD] 仍在说话... peak=$peak rms=$rms active=${active_permille}‰"
    else
        silence_count=$((silence_count + 1))
        if [ $silence_count -lt $SILENCE_LIMIT ]; then
            log "[VAD] 静默 ${silence_count}s... peak=$peak rms=$rms active=${active_permille}‰"
        fi
    fi

    if [ "$recorded_chunks" -ge "$MAX_DURATION" ]; then
        log "[VAD] 达到最大录音时长 ${MAX_DURATION}s，停止录音"
        break
    fi
done

log "[VAD] 静默 ${SILENCE_LIMIT}s，停止录音"

# 不关 LED，由 wake_monitor 控制（对话中灯常亮）

if ! finalize_wav || [ ! -f "$FINAL_WAV" ] || [ "$(wc -c < "$FINAL_WAV" 2>/dev/null)" -lt 1000 ]; then
    log "[VAD] 录音失败"
    rm -rf "$TMP_DIR"
    exit 1
fi

rm -rf "$TMP_DIR"
log "[VAD] 录音完成: $FINAL_WAV ($(wc -c < "$FINAL_WAV") bytes)"
exit 0
