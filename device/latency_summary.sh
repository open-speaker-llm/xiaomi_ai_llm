#!/bin/sh
# 音箱离线汇总：缺失值不计入样本；百分位使用 nearest-rank。
set -eu
LC_ALL=C
export LC_ALL
file="${1:-/tmp/native_first_latency.log}"
[ -r "$file" ] || { echo '没有可读取的 M03 延迟日志' >&2; exit 1; }
dir=$(mktemp -d /tmp/native_first_latency_summary.XXXXXX) || exit 1
trap 'rm -rf "$dir"' EXIT
trap 'exit 1' INT TERM
awk -v dir="$dir" '
    /\[LATENCY\] / {
        for (i=1; i<=NF; i++) {
            split($i,a,"=")
            # 固定白名单：原始日志和任意字段永不回显或用作文件名。
            if (a[1] !~ /^(wake→route|route→req|ttft|split1|tts1|commit1|wake→commit1|pcm1|wake→filler_commit|wake→answer_commit|filler→answer_gap|plan|search|filler|llm|play)$/) continue
            if (a[2] ~ /^[0-9]+([.][0-9]+)?$/) print a[2] > (dir "/" a[1])
        }
    }
' "$file"
printf 'stage seconds: n P50 P90 max\n'
for key in 'wake→route' 'route→req' ttft split1 tts1 commit1 'wake→commit1' pcm1 'wake→filler_commit' 'wake→answer_commit' 'filler→answer_gap' plan search filler llm play; do
    [ -s "$dir/$key" ] || continue
    sort -n "$dir/$key" | awk -v key="$key" '
        { v[NR]=$1 }
        END {
            if (!NR) exit
            p50=int((NR*50+99)/100); p90=int((NR*90+99)/100)
            printf "%s n=%d P50=%.3f P90=%.3f max=%.3f\n", key, NR, v[p50], v[p90], v[NR]
        }
    '
done
