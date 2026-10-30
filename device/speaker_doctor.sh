#!/bin/sh
# Read-only S12A diagnostics. Never source configuration or execute device tools.
# POSIX shell plus BusyBox awk/od/sha256sum/df; no temporary files are created.
LC_ALL=C
export LC_ALL

usage() {
    printf '%s\n' '用法：sh speaker_doctor.sh [--root 离线快照根目录]' \
        '默认只读检查当前音箱；离线模式只读取快照，缺失信息报告未知。' \
        '退出码：0=可检查项通过，1=确定缺陷，2=未知或待确认，64=参数错误。'
}

ROOT=/
OFFLINE=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0;;
        --root)
            [ "$#" -ge 2 ] && [ "$OFFLINE" = 0 ] || { usage >&2; exit 64; }
            case "$2" in /*) ;; *) usage >&2; exit 64;; esac
            ROOT=$(CDPATH= cd "$2" 2>/dev/null && pwd -P) || { usage >&2; exit 64; }
            [ "$ROOT" != / ] || { usage >&2; exit 64; }
            OFFLINE=1
            shift 2;;
        *) usage >&2; exit 64;;
    esac
done

FAILURES=0
UNCERTAINTIES=0
report() {
    printf '[%s] %s：%s\n' "$1" "$2" "$3"
    [ -z "${4:-}" ] || printf '  下一步：%s\n' "$4"
    case "$1" in FAIL) FAILURES=$((FAILURES+1));; WARN|UNKNOWN) UNCERTAINTIES=$((UNCERTAINTIES+1));; esac
}

# Reject every symlink component, including paths contained in an offline tree.
# No read may escape --root through a configured path or a manifest entry.
safe_path() (
    case "$1" in /*) ;; *) exit 1;; esac
    remaining=${1#/}
    result=${ROOT%/}
    while [ -n "$remaining" ]; do
        part=${remaining%%/*}
        if [ "$remaining" = "$part" ]; then remaining=; else remaining=${remaining#*/}; fi
        case "$part" in ''|.|..) exit 1;; esac
        result=$result/$part
        [ ! -L "$result" ] || exit 1
    done
    printf '%s\n' "${result:-/}"
)

readable_file() {
    SAFE_STATE=unsafe
    SAFE_FILE=$(safe_path "$1") || return 1
    if [ ! -e "$SAFE_FILE" ]; then SAFE_STATE=missing; return 1; fi
    SAFE_STATE=invalid
    [ -f "$SAFE_FILE" ] && [ -r "$SAFE_FILE" ] || return 1
    SAFE_STATE=ok
}
missing_report() {
    if [ "$OFFLINE" = 1 ] && [ "$SAFE_STATE" = missing ]; then
        report UNKNOWN "$1" '离线快照缺少此项，不能据此认定音箱未安装或发生故障。' "$3"
    else
        report FAIL "$1" "$2" "$3"
    fi
}

CONFIG_ROWS=
CONFIG_COMPLEX=0
if readable_file /data/native_first.env; then
    # Output is already redacted. Shell syntax is parsed, never evaluated.
    CONFIG_ROWS=$(awk '
    function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t\r]+$/, "", s); return s }
    function literal(s,    q,i,c,end,rest) {
        value=""; good=1;
        if(s~/^[ \t]+#/) return;
        s=trim(s);
        if (s=="") return;
        q=substr(s,1,1);
        if (q=="\047" || q=="\042") {
            end=0;
            for(i=2;i<=length(s);i++) {
                c=substr(s,i,1);
                if(c==q) { end=i; break }
                if(q=="\042" && (c=="$" || c=="`" || c=="\\")) good=0;
            }
            if(!end) {good=0; return}
            value=substr(s,2,end-2);rest=substr(s,end+1);
            if(rest!="" && rest!~/^[ \t]+(#.*)?$/) good=0;
        } else {
            sub(/[ \t]+#.*/, "", s); s=trim(s); value=s;
            if(s!~/^[A-Za-z0-9_.,:\/+=@%-]*$/) good=0;
        }
    }
    function interesting(k) {
        return k~/^(BACKEND|LLM_PIPELINE|TTS_ENGINE|SERVER|TTS_SERVER|LLM_API_BASE|LLM_API_KEY|DEEPSEEK_API_KEY|MINIMAX_API_KEY|GLM_API_KEY|KIMI_API_KEY|PID_FILE|DEVICE_TTS_BIN|VAD_SCRIPT|NATIVE_ASR_MANAGER|NATIVE_ASR_CTL|NATIVE_ENDPOINT_MANAGER|FOLLOWUP_ENABLED|SYSTEM1_FOLLOWUP_ENABLED|NATIVE_ENDPOINT_ENABLED|FOLLOWUP_MODE|FOLLOWUP_RECORD_MODE|SYSTEM1_FOLLOWUP_RECORD_MODE|FOLLOWUP_ASR_ENGINE|SYSTEM1_FOLLOWUP_ASR_ENGINE)$/
    }
    {
        line=trim($0);if(line=="" || line~/^#/) next;
        sub(/^export[ \t]+/, "", line);
        if(line!~/^[A-Za-z_][A-Za-z0-9_]*=/) {complex=1;next}
        key=line;sub(/=.*/, "", key);raw=substr(line,length(key)+2);
        literal(raw);if(!good) complex=1;
        if(!interesting(key)) next;
        count[key]++;state[key]=good?(value==""?"empty":"literal"):"unknown";
        if(key~/_API_KEY$/) values[key]=(value==""?"":"set");
        else if(key~/^(SERVER|TTS_SERVER|LLM_API_BASE)$/) values[key]=(value~/^https?:\/\/[^ \t]+$/?"configured":(value==""?"":"invalid"));
        else if(key~/^(PID_FILE|DEVICE_TTS_BIN|VAD_SCRIPT|NATIVE_ASR_MANAGER|NATIVE_ASR_CTL|NATIVE_ENDPOINT_MANAGER)$/) {
            if(value!="" && value!~/^\/[A-Za-z0-9_.\/-]+$/) state[key]="invalid";
            values[key]=(state[key]=="literal"?value:"");
        } else {
            if(value!="" && value!~/^[A-Za-z0-9_-]+$/) state[key]="invalid";
            values[key]=(state[key]=="literal"?value:"");
        }
    }
    END {
        print "__complex|" (complex?1:0) "||";
        for(key in count) print key "|" state[key] "|" values[key] "|" count[key];
    }' "$SAFE_FILE")
    CONFIG_COMPLEX=$(printf '%s\n' "$CONFIG_ROWS" | awk -F '|' '$1=="__complex"{print $2}')
    if [ "$CONFIG_COMPLEX" = 1 ]; then
        report UNKNOWN CONFIG '配置包含不支持的表达式或控制语句，不能静态确认运行值；未执行配置。' '将相关配置整理为独立的字面量赋值，再重新检查；不要把密钥贴到诊断报告。'
    else
        report PASS CONFIG '配置可按受支持的字面量语法读取；未执行配置。'
    fi
    duplicates=$(printf '%s\n' "$CONFIG_ROWS" | awk -F '|' '$4+0>1{n++} END{print n+0}')
    [ "$duplicates" = 0 ] || report WARN CONFIG_DUPLICATES '存在重复的受关注配置项，按最后一条字面量赋值检查。' '备份私有配置后清理重复项；诊断不会替你修改。'
else
    missing_report CONFIG '私有配置缺失、不可读或路径含符号链接。' '核对 /data/native_first.env；已有配置不要用模板覆盖，离线快照需提供经过脱敏的配置。'
    [ "$OFFLINE" != 1 ] || CONFIG_COMPLEX=1
fi

setting() {
    if [ "$CONFIG_COMPLEX" = 1 ]; then printf '?\n'; return; fi
    printf '%s\n' "$CONFIG_ROWS" | awk -F '|' -v key="$1" -v fallback="$2" '
        $1==key {found=1; if($2=="empty") print fallback; else if($2=="literal") print $3; else print "?"}
        END {if(!found) print fallback}'
}

PIPELINE=$(setting LLM_PIPELINE native)
TTS=$(setting TTS_ENGINE server)
BACKEND=$(setting BACKEND deepseek)
MODE=unknown
report INFO CONFIG_SCOPE '模式与开关按私有配置的字面量及客户端默认值推断；未读取进程环境，也未执行配置。'
case "$PIPELINE:$TTS" in
    native:device) MODE=native-device;;
    native:server) MODE=native-server;;
    server:*) MODE=server;;
esac
case "$MODE" in
    native-device) report INFO MODE 'native-device：音箱直连 LLM 与设备 TTS；仍依赖相应云服务。';;
    native-server) report INFO MODE 'native-server：音箱直连 LLM，使用自建 TTS 服务；地址隐藏，未联网。';;
    server) report INFO MODE 'server：自建服务负责 LLM 与 TTS；设备密钥不是该路线的前置条件。';;
    *) report UNKNOWN MODE '无法确认运行模式。' '检查 LLM_PIPELINE 与 TTS_ENGINE 的最后生效赋值。';;
esac
case "$BACKEND" in
    deepseek|minimax|glm|kimi) report INFO BACKEND "配置后端为 $BACKEND；未验证模型或云端凭据。";;
    *) report UNKNOWN BACKEND '后端不在设备侧已知列表或配置无法解析；未显示原始值。' '核对配置参考；server 路线还需核对服务端实际支持的后端。';;
esac
if [ "$PIPELINE" = native ]; then
    key=$(setting LLM_API_KEY '')
    if [ -z "$key" ]; then
        case "$BACKEND" in
            deepseek) key=$(setting DEEPSEEK_API_KEY '');;
            minimax) key=$(setting MINIMAX_API_KEY '');;
            glm) key=$(setting GLM_API_KEY '');;
            kimi) key=$(setting KIMI_API_KEY '');;
            *) key=?;;
        esac
    fi
    case "$key" in
        set) report PASS LLM_KEY '所选设备调用路线的密钥已填写；未显示或验证密钥。';;
        '') report FAIL LLM_KEY '所选设备调用路线缺少密钥。' '在音箱私有配置中填写所选后端密钥，勿在命令行或报告中暴露。';;
        *) report UNKNOWN LLM_KEY '不能静态判断密钥配置。' '检查高级 LLM_API_KEY 覆盖与所选后端变量。';;
    esac
else
    report SKIP LLM_KEY 'server 或未知路线不检查设备密钥；不代表服务端凭据有效。'
fi
if [ "$MODE" = server ] || [ "$MODE" = native-server ]; then
    target=$(setting SERVER configured)
    [ "$MODE" != native-server ] || target=$(setting TTS_SERVER "$target")
    case "$target" in
        configured) report INFO SERVER_TARGET '服务地址有静态配置或使用默认值；地址与查询参数均隐藏，连通性未测。';;
        *) report UNKNOWN SERVER_TARGET '服务地址缺失、不符合 http(s) 字面量或无法解析。' '在私有配置中核对 SERVER/TTS_SERVER，诊断不会访问该地址。';;
    esac
fi

BOOT=unknown
# Linux /proc/mounts is a symlink. Use this shell's numeric proc directory on
# the live speaker; offline input must be a regular, captured mounts file.
MOUNTS_PATH=/proc/mounts
[ "$OFFLINE" != 0 ] || MOUNTS_PATH=/proc/$$/mounts
if readable_file "$MOUNTS_PATH"; then
    root_device=$(awk '$2=="/"{print $1;exit}' "$SAFE_FILE")
    case "$root_device" in
        /dev/mtdblock4) BOOT=boot0; report PASS PARTITION '当前根分区为 system0（boot0，/dev/mtdblock4）。';;
        /dev/mtdblock5) BOOT=boot1; report PASS PARTITION '当前根分区为 system1（boot1，/dev/mtdblock5）。';;
        *) report UNKNOWN PARTITION '根分区不在本项目已验证映射内；未显示原始挂载数据。' '确认设备型号及活动分区，不能按旧记录推定。';;
    esac
else
    report UNKNOWN PARTITION '缺少可读的 /proc/mounts 快照。' '离线模式需补齐音箱快照；不会读取当前电脑的分区代替。'
fi
if readable_file /usr/share/mico/version; then
    firmware=$(awk '
        $1=="option" && ($2=="HARDWARE" || $2=="ROM") {
            v=$3;gsub(/[\047\042]/,"",v);
            if($2=="HARDWARE" && v=="S12A") h=1;
            if($2=="ROM" && (v=="1.54.8" || v=="1.76.54")) r=v;
        } END{print (h?"S12A":"unknown") " " (r?r:"unknown")}' "$SAFE_FILE")
    case "$firmware" in
        'S12A 1.54.8'|'S12A 1.76.54') report PASS FIRMWARE "识别到已记录组合 $firmware；这不等于 ABI 或全部功能已验收。";;
        *) report UNKNOWN FIRMWARE '型号或 ROM 不在已记录组合内；未显示原始版本文件。' '先核对硬件与固件适配，不跳过安装器 ABI 校验。';;
    esac
else
    report UNKNOWN FIRMWARE '缺少可读的 /usr/share/mico/version。' '补齐设备版本信息；不可从电脑环境推断音箱固件。'
fi

component() {
    if [ "$2" = '?' ]; then
        report UNKNOWN "$1" '组件路径无法静态确认。' '核对组件路径的字面量配置。'; return 1
    fi
    if readable_file "$2" && [ -x "$SAFE_FILE" ]; then
        report PASS "$1" '组件文件存在且可执行；诊断没有执行它。'; return 0
    fi
    missing_report "$1" '启用路线所需组件缺失、不可执行或路径含符号链接。' "$3"
    return 1
}

component CLIENT_FILE /data/native_first_client.sh '按适用安装路线恢复客户端；已有判停包需整包维护。' || :
if [ "$MODE" = native-device ]; then
    component DEVICE_TTS "$(setting DEVICE_TTS_BIN /data/ettsc)" '按设备 TTS 文档构建并安装 ettsc；不要只切换开关。' || :
else
    report SKIP DEVICE_TTS '当前模式不要求设备端 ettsc，缺失不记为故障。'
fi

pid_valid() {
    case "$1" in ''|*[!0-9]*) return 1;; esac
    [ "${#1}" -le 10 ] && [ "$1" -gt 1 ] && [ "$1" -le 2147483647 ]
}
proc_live() {
    pid_valid "$1" || return 1
    readable_file "/proc/$1/status" || return 1
    awk '$1=="State:" {found=1;if($2=="Z" || $2=="X")exit 1} END{if(!found)exit 1}' "$SAFE_FILE"
}
proc_command() {
    proc_live "$1" && readable_file "/proc/$1/cmdline" || return 1
    tr '\000' '\n' < "$SAFE_FILE" | awk -v wanted="$2" '
        NR==1 {n=split($0,a,"/");first=a[n]}
        wanted=="client" && NR==2 && (first=="sh" || first=="ash") && $0=="/data/native_first_client.sh" {found=1}
        wanted!="client" && NR==1 && first==wanted {found=1}
        END{exit !found}'
}
proc_evidence() {
    pid_valid "$1" && readable_file "/proc/$1/status" && readable_file "/proc/$1/cmdline"
}
proc_model() {
    proc_live "$1" && readable_file "/proc/$1/cmdline" || return 1
    model_form=$(tr '\000' '\n' < "$SAFE_FILE" | awk '
        {a[NR]=$0}
        END {
            d="/tmp/xiaomi_neural_shadow";
            if(NR!=8 || (a[1]!=d "/ld-linux-armhf.so.3" && a[1]!="./ld-linux-armhf.so.3") ||
               a[2]!="--library-path" || a[3]!=d || a[4]!="--preload" || a[5]!=d "/libstdc++.so.6" ||
               (a[6]!=d "/neural_pool" && a[6]!="./neural_pool") ||
               (a[7]!=d "/libsherpa-onnx-c-api.so" && a[7]!="./libsherpa-onnx-c-api.so") ||
               (a[8]!=d "/silero_vad_v5.onnx" && a[8]!="./silero_vad_v5.onnx")) {print "invalid";exit}
            if(a[1]~/^\.\// || a[6]~/^\.\// || a[7]~/^\.\// || a[8]~/^\.\//) print "relative";
            else print "absolute";
        }')
    case "$model_form" in absolute) return 0;; relative) ;; *) return 1;; esac
    if [ "$OFFLINE" = 1 ]; then
        readable_file "/proc/$1/cwd.txt" || return 2
        awk 'NR==1 && $0=="/tmp/xiaomi_neural_shadow"{ok=1} END{exit !(ok && NR==1)}' "$SAFE_FILE"
    else
        # Read the kernel symlink target as metadata only; never follow it.
        proc_dir=$(safe_path "/proc/$1") || return 2
        [ -d "$proc_dir" ] && [ -L "$proc_dir/cwd" ] || return 2
        command -v readlink >/dev/null 2>&1 || return 2
        model_cwd=$(readlink "$proc_dir/cwd" 2>/dev/null) || return 2
        [ "$model_cwd" = /tmp/xiaomi_neural_shadow ]
    fi
}
find_native() (
    proc_root=$(safe_path /proc) || exit 1
    for entry in "$proc_root"/[0-9]*/cmdline; do
        [ -f "$entry" ] || continue
        n=${entry%/cmdline};n=${n##*/}
        proc_command "$n" "$1" && printf '%s\n' "$n"
    done
)

PID_PATH=$(setting PID_FILE /tmp/native_first_client.pid)
if readable_file "$PID_PATH"; then
    client_pid=$(awk 'NR==1 && /^[0-9]+$/{p=$0} END{if(NR==1)print p}' "$SAFE_FILE")
    if [ "$OFFLINE" = 1 ] && pid_valid "$client_pid" && ! proc_evidence "$client_pid"; then
        report UNKNOWN CLIENT_PROCESS 'PID 文件存在，但缺少相应进程快照。' '补齐同一次启动的 /proc/PID/status 与 cmdline。'
    elif proc_command "$client_pid" client; then
        report PASS CLIENT_PROCESS 'PID 文件与活跃客户端命令相符；只证明进程迹象，不代表已能对话。'
    else
        report FAIL CLIENT_PROCESS 'PID 陈旧、进程不匹配或缺少对应进程快照。' '核对客户端是否启动及 PID 快照；不要按这个结果直接 kill 进程。'
    fi
else
    report UNKNOWN CLIENT_PROCESS '缺少可用的客户端 PID 文件或配置路径未知。' '核对 /tmp/native_first_client.pid 与设备实际进程；离线模式需二者快照。'
fi
MIPNS=$(find_native mipns-xiaomi)
AIVS=$(find_native mico_aivs_lab)
for daemon in MIPNS AIVS; do
    case "$daemon" in MIPNS) pids=$MIPNS;; AIVS) pids=$AIVS;; esac
    count=$(printf '%s\n' "$pids" | awk 'NF{n++} END{print n+0}')
    if [ "$count" = 1 ]; then
        report PASS "$daemon" '发现一个匹配的原生进程；尚未验证识别、云端响应或声音。'
    elif [ "$OFFLINE" = 1 ] && [ "$count" = 0 ]; then
        report UNKNOWN "$daemon" '离线快照未提供匹配的原生进程证据。' '补齐音箱 /proc 中对应进程的 cmdline 与 status，勿使用电脑进程代替。'
    else
        report FAIL "$daemon" '未发现单一活跃原生进程，可能缺失或重复。' '按排障手册核对原生服务；诊断不会重启。'
    fi
done

FOLLOWUP=$(setting FOLLOWUP_ENABLED 1)
FOLLOWUP_MODE=$(setting FOLLOWUP_MODE local_record)
RECORD=$(setting FOLLOWUP_RECORD_MODE window)
ASR_ENGINE=$(setting FOLLOWUP_ASR_ENGINE native)
ENDPOINT=$(setting NATIVE_ENDPOINT_ENABLED 0)
if [ "$BOOT" = boot1 ]; then
    FOLLOWUP=$(setting SYSTEM1_FOLLOWUP_ENABLED 0)
    RECORD=$(setting SYSTEM1_FOLLOWUP_RECORD_MODE "$RECORD")
    [ "$ASR_ENGINE" != native ] || ASR_ENGINE=$(setting SYSTEM1_FOLLOWUP_ASR_ENGINE mac)
fi
ASR_REQUIRED=0
case "$FOLLOWUP" in
    0) report SKIP FOLLOWUP '当前系统的追问开关关闭；未安装追问组件不记为故障。';;
    1)
        if [ "$FOLLOWUP_MODE" != local_record ]; then
            report UNKNOWN FOLLOWUP '配置了实验性或未知追问模式，不能按本地录音/原生实时路线判断依赖。' '核对 FOLLOWUP_MODE 对应的说明；诊断不替实验路线宣称可用。'
        elif [ "$BOOT" = boot1 ] && [ "$RECORD" = native_live ] && [ "$ASR_ENGINE" = native_live ]; then
            ASR_REQUIRED=1
            report INFO FOLLOWUP 'boot1 原生实时追问已配置；组件和运行快照继续单独检查。'
        elif [ "$BOOT" = boot0 ]; then
            report INFO FOLLOWUP 'boot0 采用本地录音与文件 ASR 路线；不是 boot1 原生实时追问。'
            component FOLLOWUP_RECORDER "$(setting VAD_SCRIPT /data/vad_record.sh)" '按快速上手上传 vad_record.sh，再验证追问。' || :
        else
            report UNKNOWN FOLLOWUP '追问模式不是本诊断支持的 boot1 native_live 组合。' '核对 record/asr 两项及对应实验路线，不能只打开追问开关。'
        fi;;
    *) report UNKNOWN FOLLOWUP '不能确认追问开关。' '使用明确的 0/1 字面量配置。';;
esac
if [ "$BOOT" = boot0 ]; then
    report SKIP ENDPOINT 'boot0 不启用 boot1 首轮判停；未安装组件不记为故障。'
    ENDPOINT=0
elif [ "$ENDPOINT" = 1 ] && [ "$BOOT" = boot1 ]; then
    ASR_REQUIRED=1
elif [ "$ENDPOINT" = 0 ]; then
    report SKIP ENDPOINT '首轮判停未启用；包存在也不代表正在运行。'
else
    report UNKNOWN ENDPOINT '不能确认首轮判停开关或适用分区。' '先确认 boot1 与 NATIVE_ENDPOINT_ENABLED=0/1。'
fi

# Only fixed-size numeric prefixes are read; dialog IDs and text are never read out.
words() {
    od -An -v -tu1 -j "$2" -N "$3" "$1" 2>/dev/null | awk -v wanted="$3" '
        {for(i=1;i<=NF;i++){v+=($i+0)*factor;n++;if(n%4==0){printf "%s%.0f",sep,v;sep=" ";v=0;factor=1}else if(n%4==1)factor=256;else factor*=256}}
        BEGIN{factor=1} END{if(n!=wanted)exit 1;print ""}'
}
plan_native_pids() (
    file=$1;offset=$((52+$2*908));owner=$3;observer=$4;deadline=$5
    first=$(words "$file" "$offset" 28)
    ids=$(words "$file" "$((offset+364))" 20)
    [ "$first" = "$(words "$file" "$offset" 28)" ] &&
        [ "$ids" = "$(words "$file" "$((offset+364))" 20)" ] || exit 2
    set -- $first
    [ "$#" = 7 ] && [ "$1" = 1314336819 ] && [ "$2" = "$owner" ] &&
        [ "$3" = "$deadline" ] && [ "$4" = 0 ] && [ "$5" = 0 ] &&
        [ "$6" = 0 ] && [ "$7" = 0 ] || exit 1
    set -- $ids
    [ "$#" = 5 ] && [ "$1" = 3 ] && [ "$2" -gt 0 ] &&
        [ "$3" = "$observer" ] && pid_valid "$4" && pid_valid "$5" || exit 1
    printf '%s %s\n' "$4" "$5"
)
ASR_PIDS=
if [ "$ASR_REQUIRED" = 1 ]; then
    component ASR_MANAGER "$(setting NATIVE_ASR_MANAGER /data/native_asr.sh)" '按匹配固件的组件安装说明恢复，已有判停包需整包维护。' || :
    component ASR_CONTROL "$(setting NATIVE_ASR_CTL /data/native_asr_ctl)" '恢复匹配版本的控制器，不运行旧版本覆盖组合包。' || :
    if ! readable_file /data/native_asr.so; then
        missing_report ASR_LIBRARY '启用的原生组件缺少可读 native_asr.so。' '核对匹配整包版本，离线快照需包含组件文件。'
    fi
    if [ "$(setting NATIVE_ASR_MANAGER /data/native_asr.sh)" != /data/native_asr.sh ] ||
       [ "$(setting NATIVE_ASR_CTL /data/native_asr_ctl)" != /data/native_asr_ctl ]; then
        report UNKNOWN ASR_SNAPSHOT '自定义管理器/控制器路径的状态布局未审核。' '为该版本补充只读诊断适配；诊断不会执行它。'
    elif readable_file /tmp/native_followup/state; then
        state_file=$SAFE_FILE
        a=$(words "$state_file" 0 32);b=$(words "$state_file" 0 32)
        size=$(wc -c < "$state_file" | tr -d ' ')
        if [ "$a" != "$b" ] || [ "$size" != 4224 ]; then
            report UNKNOWN ASR_SNAPSHOT '状态快照变化、截断或版本布局不符。' '在空闲时重新读取同版状态；不要把旧快照当作健康。'
        else
            set -- $a
            if [ "$#" != 8 ] || [ "$1" != 1312903985 ] || [ "$2" != 1 ] || [ "$8" -gt 8 ]; then
                report UNKNOWN ASR_SNAPSHOT '状态魔数或版本不符。' '核对原生组件版本；未输出状态中的文本。'
            elif [ "$OFFLINE" = 1 ] && { ! proc_evidence "$3" || ! proc_evidence "$4"; }; then
                report UNKNOWN ASR_SNAPSHOT '原生状态存在，但缺少引用进程的快照。' '补齐同次启动的进程证据，不能用电脑进程填补。'
            elif [ "$3" != "$MIPNS" ] || [ "$4" != "$AIVS" ]; then
                report FAIL ASR_SNAPSHOT '状态记录与活跃原生进程不一致。' '检查组件加载和进程重建记录；勿将其视为 healthy。'
            else
                ASR_PIDS="$3 $4"
                loaded=1;maps_missing=0;maps_bad=0
                for p in "$3" "$4"; do
                    if ! readable_file "/proc/$p/maps"; then
                        loaded=0
                        if [ "$SAFE_STATE" = missing ]; then maps_missing=1; else maps_bad=1; fi
                    elif ! awk 'NF==6 && $6=="/data/native_asr.so"{found=1} END{exit !found}' "$SAFE_FILE"; then loaded=0;maps_bad=1; fi
                done
                if [ "$8" = 7 ]; then
                    report WARN ASR_SNAPSHOT '原生状态记录失败阶段；进程存在不能证明追问恢复。' '按排障手册核对同轮结果和后续恢复，不公开原始文本。'
                elif [ "$OFFLINE" = 1 ] && [ "$maps_missing" = 1 ] && [ "$maps_bad" = 0 ]; then
                    report UNKNOWN ASR_SNAPSHOT '原生进程状态存在，但共享库映射快照不完整。' '补齐同次启动的 /proc/PID/maps，不能推定已加载或未加载。'
                elif [ "$loaded" = 1 ]; then
                    report INFO ASR_SNAPSHOT '进程、共享库和状态头相符；仅为快照就绪迹象，未确认 AEC、收音或正式 healthy。' '需要时在真人验收中核对免唤醒追问、静默退出和原生报时。'
                else
                    report FAIL ASR_SNAPSHOT '原生进程未同时显示 native_asr.so 加载证据。' '核对匹配版本的组件加载；诊断不会注入或重启。'
                fi
            fi
        fi
    else
        report UNKNOWN ASR_SNAPSHOT '缺少可读的原生状态快照；未运行带独占锁的 status 控制器。' '确认已安装组件，并在空闲时收集同版快照。'
    fi
else
    report SKIP ASR_SNAPSHOT '当前已知路线不要求 boot1 原生追问/判停组件。'
fi

PACKAGE_OK=0
PACKAGE=$(safe_path /data/native_endpoint)
if [ -n "$PACKAGE" ] && [ -d "$PACKAGE" ]; then
    if readable_file /data/native_endpoint/package.sha256; then
        manifest=$(awk '
            BEGIN{split("runtime.tar.gz native_asr.so native_first_client.sh manager.sh lifecycle",a," ");for(i in a)allow[a[i]]=1}
            NF!=2 || length($1)!=64 || $1!~/^[0-9a-fA-F]+$/ || !allow[$2] || seen[$2]++ {bad=1;next}
            {rows=rows $2 " " tolower($1) "\n";n++}
            END{if(bad || n!=5)exit 1;printf "%s",rows}' "$SAFE_FILE")
        manifest_rc=$?
        if [ "$manifest_rc" != 0 ]; then
            report FAIL ENDPOINT_HASH '安装包清单有缺项、重复或不允许的路径；未按清单读取外部文件。' '恢复经核对的五项整包清单，不跳过校验。'
        elif ! command -v sha256sum >/dev/null 2>&1; then
            report UNKNOWN ENDPOINT_HASH '缺少 sha256sum，无法校验包。' '在具备该工具的音箱或可信离线环境重新检查。'
        else
            PACKAGE_OK=1;package_missing=0;package_bad=0
            for name in runtime.tar.gz native_asr.so native_first_client.sh manager.sh lifecycle; do
                expected=$(printf '%s\n' "$manifest" | awk -v name="$name" '$1==name{print $2}')
                if readable_file "/data/native_endpoint/$name"; then
                    actual=$(sha256sum "$SAFE_FILE" 2>/dev/null | awk '{print $1}')
                    if [ "$actual" != "$expected" ]; then PACKAGE_OK=0;package_bad=1; fi
                else
                    PACKAGE_OK=0
                    if [ "$SAFE_STATE" = missing ]; then package_missing=1; else package_bad=1; fi
                fi
            done
            if [ "$PACKAGE_OK" = 1 ]; then
                report PASS ENDPOINT_HASH '整包五项摘要与清单一致；不等于来源可信、运行就绪或真人验收。'
            elif [ "$OFFLINE" = 1 ] && [ "$package_missing" = 1 ] && [ "$package_bad" = 0 ]; then
                report UNKNOWN ENDPOINT_HASH '离线清单存在，但安装包文件快照不完整。' '补齐清单中的五项文件后重试，不用电脑文件冒充设备包。'
            else
                report FAIL ENDPOINT_HASH '整包存在缺失、符号链接或摘要不匹配。' '恢复完整匹配包，不要只覆盖组合 SO 或客户端。'
            fi
        fi
    else
        missing_report ENDPOINT_HASH '存在包目录，但缺少安全可读的清单。' '保留现场并按整包维护说明核对；离线模式需补齐清单快照。'
    fi
elif [ "$ENDPOINT" = 1 ] && [ "$BOOT" = boot1 ]; then
    if [ "$OFFLINE" = 1 ] && [ -n "$PACKAGE" ] && [ ! -e "$PACKAGE" ]; then
        report UNKNOWN ENDPOINT_PACKAGE '离线快照缺少判停包，不能确定设备是否安装。' '补齐完整包与清单，或在音箱上执行只读诊断。'
    else
        report FAIL ENDPOINT_PACKAGE '启用判停但完整包未安装或包路径不安全。' '先完成匹配基线的整包安装，不能仅设置开关。'
    fi
else
    report SKIP ENDPOINT_HASH '未安装可检查的判停包；当前未明确启用时不记为缺陷。'
fi

if [ "$ENDPOINT" = 1 ] && [ "$BOOT" = boot1 ]; then
    component ENDPOINT_MANAGER "$(setting NATIVE_ENDPOINT_MANAGER /data/native_endpoint/manager.sh)" '恢复同版整包管理器。' || :
    if [ "$PACKAGE_OK" = 1 ]; then
        active_ok=1;active_missing=0;active_bad=0
        for name in native_first_client.sh native_asr.so; do
            expected=$(printf '%s\n' "$manifest" | awk -v name="$name" '$1==name{print $2}')
            if readable_file "/data/$name"; then
                actual=$(sha256sum "$SAFE_FILE" 2>/dev/null | awk '{print $1}')
                if [ "$actual" != "$expected" ]; then active_ok=0;active_bad=1; fi
            else
                active_ok=0
                if [ "$SAFE_STATE" = missing ]; then active_missing=1; else active_bad=1; fi
            fi
        done
        if [ "$active_ok" = 1 ]; then report PASS ENDPOINT_ACTIVE_HASH '活动客户端与 SO 均匹配安装包。'
        elif [ "$OFFLINE" = 1 ] && [ "$active_missing" = 1 ] && [ "$active_bad" = 0 ]; then report UNKNOWN ENDPOINT_ACTIVE_HASH '活动客户端或 SO 快照缺失，无法比较安装版本。' '补齐音箱实际 /data 下的文件快照。'
        else report FAIL ENDPOINT_ACTIVE_HASH '活动客户端或 SO 与包不一致。' '按整包维护方案恢复一致版本，不用基础追问安装器覆盖。'; fi
    fi
    if [ "$(setting NATIVE_ENDPOINT_MANAGER /data/native_endpoint/manager.sh)" != /data/native_endpoint/manager.sh ]; then
        report UNKNOWN ENDPOINT_SNAPSHOT '自定义管理器的状态布局未审核。' '补充对应版本的只读适配。'
    elif readable_file /tmp/xiaomi_native_wake_probe/native-pool.state; then
        pool_file=$SAFE_FILE
        a=$(words "$pool_file" 0 52);b=$(words "$pool_file" 0 52)
        size=$(wc -c < "$pool_file" | tr -d ' ')
        if [ "$a" != "$b" ] || [ "$size" != 3684 ]; then
            report UNKNOWN ENDPOINT_SNAPSHOT '判停快照变化、截断或布局不符。' '空闲时重新收集同版状态，不从旧日志推断 READY。'
        else
            set -- $a
            if [ "$#" != 13 ] || [ "$1" != 1313878067 ] || [ "$5" -lt 1 ] || [ "$5" -gt 4 ] || [ "$6" -ge "$5" ]; then
                report UNKNOWN ENDPOINT_SNAPSHOT '判停状态头不符合已知布局。' '核对包版本与状态文件。'
            elif [ "$7" != 1 ] || [ "${13}" != 0 ]; then
                report WARN ENDPOINT_SNAPSHOT '判停快照标记未就绪或正在排空。' '稍后在空闲状态复查；新唤醒可能使用原生收音。'
            elif [ "$OFFLINE" = 1 ] && { ! proc_evidence "$2" || ! proc_evidence "$3"; }; then
                report UNKNOWN ENDPOINT_SNAPSHOT '判停状态存在，但控制器或模型进程快照缺失。' '补齐同次启动的进程证据。'
            elif ! proc_command "$2" native_wake_pool; then
                report FAIL ENDPOINT_SNAPSHOT '判停控制器或模型进程与快照不匹配。' '检查进程和组件版本；诊断不重启模型。'
            else
                proc_model "$3";model_rc=$?
                if [ "$model_rc" = 2 ]; then
                    report UNKNOWN ENDPOINT_SNAPSHOT '模型使用相对路径，但缺少可信工作目录证据。' '离线快照补齐 /proc/PID/cwd.txt，仅保存音箱 readlink /proc/PID/cwd 的输出。'
                elif [ "$model_rc" != 0 ]; then
                    report FAIL ENDPOINT_SNAPSHOT '模型进程不符合已验证 loader、参数位置或工作目录。' '核对 run_neural_pool.sh 对应的启动形式；文件名出现在其他命令参数中不代表模型存活。'
                elif ! readable_file /proc/uptime; then
                    report UNKNOWN ENDPOINT_SNAPSHOT '缺少音箱 uptime，不能核验租约时效。' '补齐同次启动的 /proc/uptime 快照。'
                else
                    deadline=$4;active=$6
                    live=$(awk -v deadline="$deadline" '{now=int($1*1000)%4294967296;d=(deadline-now+4294967296)%4294967296;print (d>0 && d<2147483648)?1:0;exit}' "$SAFE_FILE")
                    identities=$(plan_native_pids "$pool_file" "$active" "$2" "$3" "$deadline");plan_rc=$?
                    if [ "$plan_rc" = 2 ]; then
                        report UNKNOWN ENDPOINT_SNAPSHOT '活动计划的数字快照在读取中变化。' '在空闲时重新收集同版快照。'
                    elif [ "$plan_rc" != 0 ]; then
                        report FAIL ENDPOINT_SNAPSHOT '活动计划的魔数、归属、期限、模式或阶段与池不一致。' '核对同版状态，不能把损坏或旧计划当作就绪。'
                    elif [ "$live" = 1 ] && [ -n "$ASR_PIDS" ] && [ "$identities" = "$ASR_PIDS" ]; then
                        report INFO ENDPOINT_SNAPSHOT '状态头、租约及进程身份相符；仅为快照就绪迹象，不宣称正式 ENDPOINT_READY。' '需要时用首轮静默、停顿续说与新唤醒测试确认实际行为。'
                    else
                        report FAIL ENDPOINT_SNAPSHOT '租约已过期或判停引用的原生进程不匹配。' '核对同一次启动的状态与进程；保留拒绝记录，勿清空路由日志。'
                    fi
                fi
            fi
        fi
    else
        report UNKNOWN ENDPOINT_SNAPSHOT '缺少判停状态快照；未运行带独占锁的管理器 status。' '检查同版包和音箱运行快照，不把已安装当成 READY。'
    fi
fi

DF_ROWS=
if [ "$OFFLINE" = 1 ]; then
    if readable_file /doctor/df-k.txt; then DF_ROWS=$(cat "$SAFE_FILE"); fi
else
    # df reads filesystem counters only. It is never used against offline trees.
    if command -v df >/dev/null 2>&1; then DF_ROWS=$(df -Pk /data /tmp 2>/dev/null); fi
fi
for mountpoint in /data /tmp; do
    available=$(printf '%s\n' "$DF_ROWS" | awk -v mountpoint="$mountpoint" '$NF==mountpoint && $4~/^[0-9]+$/ && length($4)<=12{print $4;exit}')
    case "$mountpoint" in /data) threshold=1024;label=DATA_SPACE;; /tmp) threshold=32768;label=TMP_SPACE;; esac
    if [ -z "$available" ]; then
        report UNKNOWN "$label" '缺少对应文件系统的空间信息。' '离线快照可提供 /doctor/df-k.txt（音箱 df -Pk /data /tmp 的输出）；不会读取电脑空间代替。'
    elif [ "$available" -lt "$threshold" ]; then
        report WARN "$label" "可用 ${available} KiB，低于诊断提示阈值 ${threshold} KiB。" '核对日志、包和运行空间；诊断不会删除文件，阈值不是安装容量保证。'
    else
        report PASS "$label" "可用 ${available} KiB；空间阈值检查通过，不代表长期稳定或升级容量充足。"
    fi
done

report INFO HUMAN_ACCEPTANCE '未进行真人语音、听觉、家居动作、云端连通或长期稳定验收。' '按本轮人工测试说明安排验证；本诊断结果不能代替这些测试。'
if [ "$OFFLINE" = 1 ]; then report INFO SNAPSHOT '离线结果只代表所提供快照；并非音箱当前实时状态。'; fi
printf 'DOCTOR_SUMMARY failures=%s uncertainties=%s human_acceptance=not_run\n' "$FAILURES" "$UNCERTAINTIES"
[ "$FAILURES" = 0 ] || exit 1
[ "$UNCERTAINTIES" = 0 ] || exit 2
exit 0
