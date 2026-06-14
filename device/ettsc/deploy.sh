#!/bin/bash
# 把 dist/ettsc 推到音箱 /data/ettsc。
# 用法: ./deploy.sh [host]   默认 192.168.8.152
set -e
cd "$(dirname "$0")"
HOST="${1:-192.168.8.152}"
SSHOPT=(-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa)

[ -f dist/ettsc ] || { echo "先 ./build.sh"; exit 1; }
echo "[deploy] -> root@$HOST:/data/ettsc"
scp "${SSHOPT[@]}" -O dist/ettsc "root@$HOST:/data/ettsc"
ssh "${SSHOPT[@]}" "root@$HOST" 'chmod +x /data/ettsc && /data/ettsc rawtcp 127.0.0.1:1 2>&1 | head -1; echo deployed'
echo "[deploy] 自检：SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt /data/ettsc probe"
