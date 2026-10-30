# Pure stdin/stdout protocol functions. No configuration, device or network I/O.
# This source is embedded into native_first_client.sh; do not source it on-device.

json_escape() {
    # od preserves record separators and trailing newlines, unlike line-based sed.
    # Both utilities are already supplied by the speaker's BusyBox.
    LC_ALL=C od -An -v -t u1 | LC_ALL=C awk '
        { for (i = 1; i <= NF; i++) {
            n = $i + 0;
            if (n == 34) printf "\\\"";
            else if (n == 92) printf "\\\\";
            else if (n == 8) printf "\\b";
            else if (n == 9) printf "\\t";
            else if (n == 10) printf "\\n";
            else if (n == 12) printf "\\f";
            else if (n == 13) printf "\\r";
            else if (n < 32) printf "\\u%04x", n;
            else printf "%c", n;
        } fflush(); }
    '
}

json_unicode_decode() {
    # One escaped JSON string per line. Speech text normalizes CR/LF/tab to
    # spaces and omits the other control characters, keeping one output record.
    LC_ALL=C awk '
function hv(c) { return index("0123456789abcdef", tolower(c)) - 1 }
function hex4(h,    j, v, n) {
    if (length(h) != 4) return -1;
    n = 0;
    for (j = 1; j <= 4; j++) {
        v = hv(substr(h, j, 1));
        if (v < 0) return -1;
        n = n * 16 + v;
    }
    return n;
}
function emit(n) {
    if (n == 9 || n == 10 || n == 13) printf " ";
    else if (n < 32) return;
    else if (n < 128) printf "%c", n;
    else if (n < 2048) printf "%c%c", 192 + int(n / 64), 128 + (n % 64);
    else if (n < 65536) printf "%c%c%c", 224 + int(n / 4096), 128 + (int(n / 64) % 64), 128 + (n % 64);
    else printf "%c%c%c%c", 240 + int(n / 262144), 128 + (int(n / 4096) % 64), 128 + (int(n / 64) % 64), 128 + (n % 64);
}
{
    for (i = 1; i <= length($0); i++) {
        c = substr($0, i, 1);
        if (c == "\\" && i < length($0)) {
            c = substr($0, ++i, 1);
            if (c == "u" && (n = hex4(substr($0, i + 1, 4))) >= 0) {
                i += 4;
                if (n >= 55296 && n <= 56319 && substr($0, i + 1, 2) == "\\u") {
                    low = hex4(substr($0, i + 3, 4));
                    if (low >= 56320 && low <= 57343) {
                        n = 65536 + (n - 55296) * 1024 + low - 56320;
                        i += 6;
                    }
                }
                if (n >= 55296 && n <= 57343) n = 65533;
                emit(n);
                continue;
            }
            if (c == "n" || c == "r" || c == "t") c = " ";
            else if (c == "b" || c == "f") c = "";
            else if (c != "\\" && c != "\"" && c != "/") c = "\\" c;
        }
        printf "%s", c;
    }
    printf "\n";
    fflush();
}'
}

json_text_unescape() {
    json_unicode_decode
}

# Xiaomi logs may have a timestamp before JSON. Return the first text string
# without treating escaped quotes as the end; the caller decodes its contents.
json_text_field() {
    LC_ALL=C awk '
        match($0, /"text"[ \t]*:[ \t]*"([^"\\]|\\.)*"/) {
            s = substr($0, RSTART, RLENGTH);
            sub(/^"text"[ \t]*:[ \t]*"/, "", s);
            print substr(s, 1, length(s) - 1);
            fflush();
        }
    '
}

# OpenAI-compatible SSE -> speech text. Validate a complete JSON event before
# publishing its content; memory is bounded per event, never by the whole reply.
# Existing callers read complete/incomplete from $1 after the pipe closes.
llm_sse_content() {
    LC_ALL=C awk -v status_file="${1:-}" '
function bad() { parse_error = 2; return 0 }
function need() { parse_error = 1; return 0 }
function ws() { while (pos <= size && substr(src, pos, 1) ~ /[ \t\r\n]/) pos++ }
function hex4(h,    i,n,v) {
    if (length(h) != 4) return -1;
    n = 0;
    for (i = 1; i <= 4; i++) {
        v = index("0123456789abcdef", tolower(substr(h, i, 1))) - 1;
        if (v < 0) return -1;
        n = n * 16 + v;
    }
    return n;
}
function string_value(    begin,c,e,n,low) {
    if (substr(src, pos, 1) != "\"") return bad();
    begin = ++pos;
    while (pos <= size) {
        c = substr(src, pos++, 1);
        if (c == "\"") { raw = substr(src, begin, pos - begin - 1); return 1 }
        if (c in controls) return bad();
        if (c != "\\") continue;
        if (pos > size) return need();
        e = substr(src, pos++, 1);
        if (e == "u") {
            if (pos + 3 > size) return need();
            n = hex4(substr(src, pos, 4)); pos += 4;
            if (n < 0) return bad();
            if (n >= 55296 && n <= 56319) {
                if (pos + 5 > size) return need();
                if (substr(src, pos, 2) != "\\u") return bad();
                low = hex4(substr(src, pos + 2, 4)); pos += 6;
                if (low < 56320 || low > 57343) return bad();
            } else if (n >= 56320 && n <= 57343) return bad();
        } else if (e !~ /^["\\\/bfnrt]$/) return bad();
    }
    return need();
}
function key_name(s,    i,c,n,out) {
    out = "";
    for (i = 1; i <= length(s); i++) {
        c = substr(s, i, 1);
        if (c == "\\") {
            c = substr(s, ++i, 1);
            if (c == "u") {
                n = hex4(substr(s, i + 1, 4)); i += 4;
                c = (n < 128 ? sprintf("%c", n) : "?");
            }
        }
        out = out c;
    }
    return out;
}
function field_role(role,key) {
    if (role == "root" && key == "choices") return "choices";
    if (role == "root" && key == "error") return "error";
    if (role == "choice" && key == "delta") return "delta";
    if (role == "choice" && key == "index") return "index";
    if (role == "choice" && key == "finish_reason") return "finish";
    if (role == "delta" && key == "content") return "content";
    return "ignore";
}
function value(role,depth,    c,key,child,count,token,r) {
    if (depth > 32) return bad();
    ws(); if (pos > size) return need();
    c = substr(src, pos, 1);
    if (role == "root" && c != "{") return bad();
    if (role == "choices" && c != "[") return bad();
    if (role == "choice" && c != "{") return bad();
    if (role == "index" && c !~ /^[0-9]$/) return bad();
    if (role == "delta" && c != "{" && substr(src,pos,4) != "null") return bad();
    if ((role == "content" || role == "finish") && c != "\"" && substr(src,pos,4) != "null") return bad();
    if (role == "error" && substr(src,pos,4) != "null") event_error = 1;
    if (c == "{") {
        pos++; ws(); if (pos > size) return need();
        if (substr(src,pos,1) == "}") { pos++; return 1 }
        while (1) {
            if (!string_value()) return 0;
            key = key_name(raw); ws();
            if (pos > size) return need();
            if (substr(src,pos++,1) != ":") return bad();
            child = field_role(role,key);
            if (!value(child,depth+1)) return 0;
            ws(); if (pos > size) return need();
            c = substr(src,pos++,1);
            if (c == "}") return 1;
            if (c != ",") return bad();
            ws(); if (pos > size) return need();
        }
    }
    if (c == "[") {
        pos++; ws(); count = 0; if (pos > size) return need();
        if (substr(src,pos,1) == "]") { pos++; return 1 }
        while (1) {
            if (role == "choices") {
                choice_text = ""; choice_finish = ""; choice_index = count;
                choice_content_seen = choice_finish_seen = choice_index_seen = 0;
            }
            if (!value(role == "choices" ? "choice" : "ignore",depth+1)) return 0;
            if (role == "choices" && choice_index == 0) {
                if (event_choice_seen++) return bad();
                event_text = choice_text;
                if (choice_finish == "stop") event_complete = 1;
                else if (choice_finish != "") event_error = 1;
            }
            count++; ws(); if (pos > size) return need();
            c = substr(src,pos++,1);
            if (c == "]") return 1;
            if (c != ",") return bad();
        }
    }
    if (c == "\"") {
        if (!string_value()) return 0;
        if (role == "content") {
            if (choice_content_seen++) return bad();
            choice_text = raw;
        } else if (role == "finish") {
            if (choice_finish_seen++) return bad();
            choice_finish = key_name(raw);
            if (choice_finish == "") event_error = 1;
        } else if (role == "index") return bad();
        return 1;
    }
    r = substr(src,pos);
    if (r ~ /^(null|true|false)/) {
        match(r,/^(null|true|false)/); token = substr(r,1,RLENGTH); pos += RLENGTH;
        if (role == "index" || ((role == "content" || role == "finish") && token != "null")) return bad();
        return 1;
    }
    if (match(r,/^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/)) {
        token = substr(r,1,RLENGTH); pos += RLENGTH;
        if (role == "index") {
            if (choice_index_seen++ || token !~ /^(0|[1-9][0-9]*)$/) return bad();
            choice_index = token + 0;
        }
        return 1;
    }
    return bad();
}
function consume(    ok) {
    src = buffer; size = length(src); pos = 1; parse_error = 0;
    event_error = event_complete = event_choice_seen = 0; event_text = "";
    ok = value("root",0); ws();
    if (!ok) return parse_error;
    if (pos <= size) return 2;
    if (event_error || (finished && event_text != "")) { failed = 1; return 0 }
    if (event_text != "") { print event_text; fflush() }
    if (event_complete) { complete = 1; finished = 1 }
    return 0;
}
BEGIN { for (i=0; i<32; i++) controls[sprintf("%c",i)] = 1 }
{
    sub(/\r$/, "");
    if ($0 == "") {
        if (buffer != "") failed = 1;
        buffer = ""; event_type = ""; next;
    }
    if ($0 ~ /^:/) next;
    if ($0 ~ /^event:/) {
        event_type = $0; sub(/^event:[ \t]*/, "", event_type);
        if (event_type == "error") failed = 1;
        next;
    }
    if ($0 !~ /^data:/) next;
    if (failed) next;
    data = $0; sub(/^data: ?/, "", data);
    if (data ~ /^[ \t]*\[DONE\][ \t]*$/) {
        if (buffer != "") failed = 1;
        else complete = done = 1;
        next;
    }
    if (done) { failed = 1; next }
    buffer = (buffer == "" ? data : buffer "\n" data);
    if (length(buffer) > 262144) { failed = 1; buffer = ""; next }
    result = consume();
    if (result == 2) failed = 1;
    if (result != 1) buffer = "";
}
END {
    if (buffer != "") failed = 1;
    if (status_file != "") {
        print (complete && !failed ? "complete" : "incomplete") > status_file;
        close(status_file);
    }
}
    ' | json_unicode_decode
}
