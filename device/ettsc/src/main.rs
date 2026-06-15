// 端侧 EdgeTTS 客户端（纯阻塞 IO + rustls，不用 tokio）。
// 用法:
//   ettsc "文本" [out.mp3] [voice]   合成并落盘
//   ettsc probe                       只测 wss 握手（看 101 / 错误）
//
// tokio 的 epoll 异步 reactor 在这台音箱（musl 静态 / kernel 4.9）上不工作，故用阻塞。
// rustls 自带 webpki 根证书，无需 SSL_CERT_FILE。
use sha2::{Digest, Sha256};
use std::net::TcpStream;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tungstenite::Message;

const TRUSTED: &str = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
const HOST: &str = "speech.platform.bing.com";
// 微软会不定期抬高最低 Chromium 版本导致旧值 403。可用环境变量覆盖，过期时只改配置、无需重编。
const DEFAULT_GEC_VERSION: &str = "1-143.0.3650.75";
const DEFAULT_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0";
const DEFAULT_ORIGIN: &str = "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold";
// 输出格式：默认 MP3（兼容老用法）；句级流式连播用 raw PCM（headerless，可直接灌 aplay）。
// 可用 ETTSC_FORMAT 覆盖，如 raw-24khz-16bit-mono-pcm。
const DEFAULT_FORMAT: &str = "audio-24khz-48kbitrate-mono-mp3";

fn env_or(key: &str, default: &str) -> String {
    match std::env::var(key) {
        Ok(v) if !v.is_empty() => v,
        _ => default.to_string(),
    }
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

fn build_request() -> tungstenite::handshake::client::Request {
    let url = format!(
        "wss://{HOST}/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken={TRUSTED}&Sec-MS-GEC={}&Sec-MS-GEC-Version={}&ConnectionId={}",
        sec_ms_gec(),
        env_or("ETTSC_GEC_VERSION", DEFAULT_GEC_VERSION),
        hexid()
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
        .header("Origin", env_or("ETTSC_ORIGIN", DEFAULT_ORIGIN))
        .header("Pragma", "no-cache")
        .header("Cache-Control", "no-cache")
        .header("Accept-Encoding", "gzip, deflate, br, zstd")
        .header("Accept-Language", "en-US,en;q=0.9")
        .header("User-Agent", env_or("ETTSC_UA", DEFAULT_UA))
        .body(())
        .unwrap()
}

// 阻塞建链：TCP（带超时）→ rustls TLS → WebSocket 升级握手。
fn connect() -> tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<TcpStream>> {
    let tcp = TcpStream::connect((HOST, 443)).expect("tcp connect");
    tcp.set_read_timeout(Some(Duration::from_secs(20))).ok();
    tcp.set_write_timeout(Some(Duration::from_secs(20))).ok();
    let (ws, resp) = tungstenite::client_tls(build_request(), tcp).unwrap_or_else(|e| {
        eprintln!("[!] ws handshake failed: {e}");
        std::process::exit(2);
    });
    eprintln!("[+] handshake OK, HTTP {}", resp.status());
    ws
}

fn main() {
    let a: Vec<String> = std::env::args().collect();

    if a.get(1).map(|s| s == "probe").unwrap_or(false) {
        eprintln!("[*] probe ...");
        let mut ws = connect();
        let _ = ws.close(None);
        return;
    }

    let text = a.get(1).cloned().unwrap_or_else(|| "你好，这是音箱端直连 EdgeTTS 测试。".into());
    let out = a.get(2).cloned().unwrap_or_else(|| "/tmp/edgetts.mp3".into());
    let voice = a.get(3).cloned().unwrap_or_else(|| "zh-CN-YunjianNeural".into());

    eprintln!("[*] connecting ...");
    let mut ws = connect();

    let date = chrono::Utc::now()
        .format("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)")
        .to_string();
    let fmt = env_or("ETTSC_FORMAT", DEFAULT_FORMAT);
    let cfg = format!(
        "X-Timestamp:{date}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n{{\"context\":{{\"synthesis\":{{\"audio\":{{\"metadataoptions\":{{\"sentenceBoundaryEnabled\":\"false\",\"wordBoundaryEnabled\":\"false\"}},\"outputFormat\":\"{fmt}\"}}}}}}}}"
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
    // ETTSC_PCM=1：本地把 mp3 解码成裸 PCM(S16LE) 输出，供 aplay 连续播放（句级流式无缝）。
    // 默认仍输出原始 mp3（兼容 miplayer --file 老用法）。
    if env_or("ETTSC_PCM", "") == "1" {
        // aplay 经 Master 衰减后比 miplayer 偏小，用 ETTSC_GAIN 数字增益追平（默认 1.0 不变）。
        let gain: f32 = env_or("ETTSC_GAIN", "1.0").parse().unwrap_or(1.0);
        let pcm = decode_mp3_to_pcm(&audio, gain);
        std::fs::write(&out, &pcm).unwrap();
        eprintln!("[+] done: {frames} frames, {} mp3 bytes -> {} pcm bytes -> {out}", audio.len(), pcm.len());
        if pcm.is_empty() {
            std::process::exit(3);
        }
    } else {
        std::fs::write(&out, &audio).unwrap();
        eprintln!("[+] done: {frames} frames, {} bytes -> {out}", audio.len());
        if audio.is_empty() {
            std::process::exit(3);
        }
    }
}

// mp3 → 裸 PCM(S16LE 交织)。EdgeTTS 输出为单声道 24kHz，故 PCM 也是 24kHz/mono。
// gain：数字增益（>1 放大），超出 i16 范围则削顶（clamp），避免溢出。
fn decode_mp3_to_pcm(mp3: &[u8], gain: f32) -> Vec<u8> {
    let mut dec = minimp3::Decoder::new(mp3);
    let mut out: Vec<u8> = Vec::new();
    let apply = (gain - 1.0).abs() > 0.001;
    let mut peak: i32 = 0;
    loop {
        match dec.next_frame() {
            Ok(minimp3::Frame { data, .. }) => {
                for s in data {
                    let a = (s as i32).abs();
                    if a > peak {
                        peak = a;
                    }
                    let v = if apply {
                        (s as f32 * gain).round().clamp(-32768.0, 32767.0) as i16
                    } else {
                        s
                    };
                    out.extend_from_slice(&v.to_le_bytes());
                }
            }
            Err(minimp3::Error::Eof) => break,
            Err(e) => {
                eprintln!("[!] mp3 decode err: {e:?}");
                break;
            }
        }
    }
    let headroom = if peak > 0 { 32767.0 / peak as f32 } else { 0.0 };
    eprintln!("[*] pcm peak={peak}/32767 ({:.0}%), 无削顶最大增益≈{headroom:.2}x", peak as f32 / 32767.0 * 100.0);
    out
}
