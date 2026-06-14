// 端侧 EdgeTTS 客户端（纯阻塞 IO，不用 tokio —— 该音箱上 tokio epoll reactor 不工作）。
// 用法:
//   ettsc "文本" [out.mp3] [voice]                合成并落盘
//   ettsc probe [tls12|all]                        只测 wss 握手
//   ettsc rawtcp host:port                         纯阻塞 TCP 收发自检
use sha2::{Digest, Sha256};
use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tungstenite::Message;

const TRUSTED: &str = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
const HOST: &str = "speech.platform.bing.com";
// 微软会不定期抬高最低 Chromium 版本导致旧值 403。这两个值可用环境变量覆盖，
// 过期时只改配置（对照最新 edge-tts 的 constants.py），无需重编。
const DEFAULT_GEC_VERSION: &str = "1-143.0.3650.75";
const DEFAULT_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0";

// 空串视同未设（shell 传空值时用内置默认）
fn env_or(key: &str, default: &str) -> String {
    match std::env::var(key) {
        Ok(v) if !v.is_empty() => v,
        _ => default.to_string(),
    }
}
fn gec_version() -> String {
    env_or("ETTSC_GEC_VERSION", DEFAULT_GEC_VERSION)
}
fn user_agent() -> String {
    env_or("ETTSC_UA", DEFAULT_UA)
}
fn origin() -> String {
    env_or("ETTSC_ORIGIN", "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold")
}

fn sec_ms_gec() -> String {
    let unix = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64;
    let mut ticks = unix + 11_644_473_600;
    ticks -= ticks % 300;
    let ticks100ns: i128 = (ticks as i128) * 10_000_000;
    let s = format!("{}{}", ticks100ns, TRUSTED);
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    h.finalize().iter().map(|b| format!("{:02X}", b)).collect()
}

fn hexid() -> String {
    let mut buf = [0u8; 16];
    getrandom::getrandom(&mut buf).unwrap();
    buf.iter().map(|b| format!("{:02x}", b)).collect()
}

// 建立到 EdgeTTS 的阻塞 TLS 流。tls12=true 时封顶 TLS1.2（ClientHello 像 curl/OpenSSL1.0.2，过老代理）。
fn tls_connect(tls12: bool) -> native_tls::TlsStream<TcpStream> {
    let tcp = TcpStream::connect((HOST, 443)).expect("tcp connect");
    tcp.set_read_timeout(Some(Duration::from_secs(20))).ok();
    tcp.set_write_timeout(Some(Duration::from_secs(20))).ok();
    let mut b = native_tls::TlsConnector::builder();
    if tls12 {
        b.max_protocol_version(Some(native_tls::Protocol::Tlsv12));
    }
    if std::env::var("ETTSC_INSECURE").is_ok() {
        b.danger_accept_invalid_certs(true);
    }
    let conn = b.build().expect("tls builder");
    conn.connect(HOST, tcp).expect("tls handshake")
}

fn build_request(token: &str, conn_id: &str) -> tungstenite::handshake::client::Request {
    let url = format!(
        "wss://{HOST}/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken={TRUSTED}&Sec-MS-GEC={token}&Sec-MS-GEC-Version={}&ConnectionId={conn_id}",
        gec_version()
    );
    let mut key = [0u8; 16];
    getrandom::getrandom(&mut key).unwrap();
    use base64::Engine;
    let ws_key = base64::engine::general_purpose::STANDARD.encode(key);
    tungstenite::handshake::client::Request::builder()
        .method("GET")
        .uri(url)
        .header("Host", HOST)
        .header("Connection", "Upgrade")
        .header("Upgrade", "websocket")
        .header("Sec-WebSocket-Version", "13")
        .header("Sec-WebSocket-Key", ws_key)
        .header("Origin", origin())
        .header("Pragma", "no-cache")
        .header("Cache-Control", "no-cache")
        .header("Accept-Encoding", "gzip, deflate, br, zstd")
        .header("Accept-Language", "en-US,en;q=0.9")
        .header("User-Agent", user_agent())
        .body(())
        .unwrap()
}

fn main() {
    let a: Vec<String> = std::env::args().collect();

    // 自检：纯阻塞 TCP 收发
    if a.len() >= 3 && a[1] == "rawtcp" {
        eprintln!("[*] rawtcp connect {}", a[2]);
        let mut s = TcpStream::connect(&a[2]).expect("connect");
        eprintln!("[+] connected, writing ...");
        s.write_all(b"PING\r\n").expect("write");
        eprintln!("[+] wrote ok");
        let mut buf = [0u8; 128];
        s.set_read_timeout(Some(Duration::from_secs(6))).ok();
        match s.read(&mut buf) {
            Ok(n) => eprintln!("[+] read {n} bytes"),
            Err(e) => eprintln!("[!] read err {e}"),
        }
        return;
    }

    let tls12 = a.get(2).map(|s| s == "tls12").unwrap_or(true);

    // 只测握手
    if a.len() >= 2 && a[1] == "probe" {
        eprintln!("[*] probe (tls12={tls12}) ...");
        let stream = tls_connect(tls12);
        eprintln!("[+] TLS up; ws handshake ...");
        let req = build_request(&sec_ms_gec(), &hexid());
        match tungstenite::client(req, stream) {
            Ok((mut ws, resp)) => {
                eprintln!("[+] handshake OK, HTTP {}", resp.status());
                let _ = ws.close(None);
            }
            Err(e) => eprintln!("[!] ws handshake failed: {e}"),
        }
        return;
    }

    // 合成
    let text = a.get(1).cloned().unwrap_or_else(|| "你好，这是音箱端直连 EdgeTTS 测试。".into());
    let out = a.get(2).cloned().unwrap_or_else(|| "/tmp/edgetts.mp3".into());
    let voice = a.get(3).cloned().unwrap_or_else(|| "zh-CN-YunyangNeural".into());

    eprintln!("[*] TLS connect ...");
    let stream = tls_connect(true);
    let req = build_request(&sec_ms_gec(), &hexid());
    let (mut ws, resp) = match tungstenite::client(req, stream) {
        Ok(x) => x,
        Err(e) => {
            eprintln!("[!] ws handshake failed: {e}");
            std::process::exit(2);
        }
    };
    eprintln!("[+] handshake OK, HTTP {}", resp.status());

    let date = chrono::Utc::now()
        .format("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)")
        .to_string();
    let cfg = format!(
        "X-Timestamp:{date}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n{{\"context\":{{\"synthesis\":{{\"audio\":{{\"metadataoptions\":{{\"sentenceBoundaryEnabled\":\"false\",\"wordBoundaryEnabled\":\"false\"}},\"outputFormat\":\"audio-24khz-48kbitrate-mono-mp3\"}}}}}}}}"
    );
    ws.send(Message::Text(cfg)).unwrap();
    let ssml = format!(
        "X-RequestId:{}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:{date}Z\r\nPath:ssml\r\n\r\n<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'><voice name='{voice}'><prosody pitch='+0Hz' rate='+0%' volume='+0%'>{text}</prosody></voice></speak>",
        hexid()
    );
    ws.send(Message::Text(ssml)).unwrap();
    eprintln!("[*] sent config+ssml, receiving ...");

    let mut audio: Vec<u8> = Vec::new();
    let mut frames = 0u32;
    loop {
        match ws.read() {
            Ok(Message::Text(t)) => {
                let path = t.lines().find(|l| l.starts_with("Path:")).unwrap_or("");
                eprintln!("[text] {path}");
                if t.contains("Path:turn.end") {
                    break;
                }
            }
            Ok(Message::Binary(b)) => {
                if b.len() < 2 {
                    continue;
                }
                let hlen = ((b[0] as usize) << 8) | (b[1] as usize);
                let start = 2 + hlen;
                if start <= b.len() {
                    audio.extend_from_slice(&b[start..]);
                    frames += 1;
                }
            }
            Ok(Message::Close(_)) => break,
            Ok(_) => {}
            Err(e) => {
                eprintln!("[!] read err: {e}");
                break;
            }
        }
    }
    std::fs::write(&out, &audio).unwrap();
    eprintln!("[+] done: {frames} frames, {} bytes -> {out}", audio.len());
    if audio.is_empty() {
        std::process::exit(3);
    }
}
