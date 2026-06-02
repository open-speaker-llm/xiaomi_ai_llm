#!/bin/bash
# 启动客户端 (麦克风模式)

cd "$(dirname "$0")"

# 设置服务器地址
SERVER_URL="${SERVER_URL:-ws://localhost:8080/ws/voice}"

python device/audio_capture.py --mode mic --server "$SERVER_URL"
