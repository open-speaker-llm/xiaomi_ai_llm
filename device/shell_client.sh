#!/bin/sh
#
# 小米AI音箱 Shell 语音对话客户端
# 用 arecord + curl + aplay 实现端到端语音对话
#
# 部署到音箱: 通过 nc 粘贴到 /data/shell_client.sh
# 运行: sh /data/shell_client.sh
#

SERVER="${SERVER:-http://192.168.10.124:8080}"
RECORD_SECS="${RECORD_SECS:-5}"
SAMPLE_RATE="${SAMPLE_RATE:-32000}"

# ALSA 设备节点检查/创建
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

    # 解除硬件静音
    amixer -c 0 sset 'Hard Mute' off 2>/dev/null
    amixer -c 0 sset 'Ch1' unmute 2>/dev/null
    amixer -c 0 sset 'Ch2' unmute 2>/dev/null
    amixer -c 0 sset 'Master' 200 2>/dev/null
}

# 等待服务器就绪
wait_server() {
    echo "Checking server: $SERVER"
    while ! curl -s -o /dev/null -m 2 "$SERVER/"; do
        echo "  waiting for server..."
        sleep 2
    done
    echo "  server ready!"
}

echo "=== 小米AI音箱 语音对话客户端 ==="
echo "Server: $SERVER"
echo "Record: ${RECORD_SECS}s @ ${SAMPLE_RATE}Hz"

setup_audio
wait_server

while true; do
    echo ""
    echo "[Recording ${RECORD_SECS}s...]"

    # 录音
    if ! arecord -D hw:0,2 -f S16_LE -r "$SAMPLE_RATE" -c 1 -d "$RECORD_SECS" /tmp/voice_in.wav 2>/dev/null; then
        echo "Record failed, retrying..."
        sleep 1
        continue
    fi

    SIZE=$(ls -l /tmp/voice_in.wav | awk '{print $5}')
    if [ "$SIZE" -lt 1000 ]; then
        echo "Recording too small ($SIZE bytes), skipping..."
        sleep 1
        continue
    fi

    echo "[Sending ${SIZE} bytes...]"

    # 发送到服务器，接收 TTS 音频
    HTTP_CODE=$(curl -s -o /tmp/voice_out.wav -w "%{http_code}" \
        -m 30 \
        -F "file=@/tmp/voice_in.wav" \
        "$SERVER/api/v1/shell/chat")

    if [ "$HTTP_CODE" != "200" ]; then
        echo "Server error: HTTP $HTTP_CODE"
        sleep 1
        continue
    fi

    OUT_SIZE=$(ls -l /tmp/voice_out.wav 2>/dev/null | awk '{print $5}')
    if [ -z "$OUT_SIZE" ] || [ "$OUT_SIZE" -lt 100 ]; then
        echo "No response audio"
        continue
    fi

    echo "[Playing ${OUT_SIZE} bytes...]"

    # 播放 TTS 音频
    aplay -D hw:0,1 /tmp/voice_out.wav 2>/dev/null

    # 短暂停顿，避免立即重新录音
    sleep 1
done
