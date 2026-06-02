#!/bin/bash
# 启动服务器

cd "$(dirname "$0")"

# 加载环境变量
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# 启动服务
.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8080 --reload
