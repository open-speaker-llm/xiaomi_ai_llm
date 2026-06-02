#!/bin/sh
#
# 小米AI音箱 LLM 对话助手 v9 — Phase B KWS 唤醒词
#

SERVER="${SERVER:-http://192.168.8.150:8080}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

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
    amixer -c 0 sset 'Master' 224 2>/dev/null
}

setup_dsnoop() {
    if [ -f /tmp/dsnoop_ready ]; then
        return 0
    fi
    log "[SETUP] 配置 dsnoop + KwsCapture..."

    for i in 1 2 3 4 5; do
        umount /etc/asound.conf 2>/dev/null
        umount /usr/lib/libxaudio_engine.so 2>/dev/null
    done

    # 合并原始配置 + Capture + KwsCapture
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

    # Patch libxaudio_engine.so
    if [ ! -f /tmp/libxaudio_engine_patched.so ]; then
        cp /usr/lib/libxaudio_engine.so /tmp/libxaudio_engine_patched.so
        echo -n -e 'noop\x00\x00' | dd of=/tmp/libxaudio_engine_patched.so \
            bs=1 count=6 seek=700428 conv=notrunc 2>/dev/null
    fi
    mount --bind /tmp/libxaudio_engine_patched.so /usr/lib/libxaudio_engine.so 2>/dev/null

    # 重启 mipns
    killall mipns-xiaomi 2>/dev/null
    sleep 1
    /usr/bin/mipns-xiaomi -c /usr/share/xiaomi/xaudio_engine.conf 2>/dev/null &
    sleep 2

    touch /tmp/dsnoop_ready
    log "[SETUP] dsnoop + KwsCapture 就绪"
}

# ─── 主入口 ───
log "=== 小米AI音箱 LLM 对话助手 v9 (KWS) ==="
log "Server: $SERVER"

setup_audio
setup_dsnoop

curl -s -o /dev/null -m 2 "$SERVER/" && log "服务器连接正常" || log "服务器无法连接"

# 冻结 mipns 防止小爱抢答
log "[INIT] 冻结小爱进程"
killall -STOP mipns-xiaomi 2>/dev/null

# 启动对话状态机
exec sh /data/wake_monitor.sh
