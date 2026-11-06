// 端侧 EdgeTTS 客户端（纯阻塞 IO + rustls，不用 tokio）。
// 用法:
//   ettsc "文本" [out.mp3] [voice]   合成并落盘
//   ettsc probe                       只测 wss 握手（看 101 / 错误）
//
// tokio 的 epoll 异步 reactor 在这台音箱（musl 静态 / kernel 4.9）上不工作，故用阻塞。
// rustls 自带 webpki 根证书，无需 SSL_CERT_FILE。
use sha2::{Digest, Sha256};
use std::net::TcpStream;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tungstenite::Message;
mod gec_v2;
mod prewarm;
mod persistent;
mod stream_pcm;

const TRUSTED: &str = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
const HOST: &str = "speech.platform.bing.com";
// 版本前缀选择鉴权算法，Chromium 部分可通过环境变量覆盖。
const DEFAULT_GEC_VERSION: &str = "2-143.0.3650.75";
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

fn sec_ms_gec_at(version: &str, unix: u64) -> Result<String, &'static str> {
    if version.starts_with("2-") {
        return Ok(gec_v2::generate(unix, TRUSTED));
    }
    if !version.starts_with("1-") {
        return Err("unsupported ETTSC_GEC_VERSION: expected 2-<Chromium version> or legacy 1-<version>");
    }
    let mut ticks = u128::from(unix) + 11_644_473_600;
    ticks -= ticks % 300;
    let ticks100ns = ticks * 10_000_000;
    let s = format!("{}{}", ticks100ns, TRUSTED);
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    Ok(h.finalize().iter().map(|b| format!("{:02X}", b)).collect())
}

fn hexid() -> String {
    let mut buf = [0u8; 16];
    getrandom::getrandom(&mut buf).unwrap();
    buf.iter().map(|b| format!("{:02x}", b)).collect()
}

fn build_request() -> tungstenite::handshake::client::Request {
    let version = env_or("ETTSC_GEC_VERSION", DEFAULT_GEC_VERSION);
    let unix = SystemTime::now().duration_since(UNIX_EPOCH).expect("system clock before Unix epoch").as_secs();
    let token = sec_ms_gec_at(&version, unix).unwrap_or_else(|error| {
        eprintln!("[!] {error}");
        std::process::exit(2);
    });
    eprintln!("[*] Sec-MS-GEC v{} version={version}", version.split('-').next().unwrap());
    let url = format!(
        "wss://{HOST}/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken={TRUSTED}&Sec-MS-GEC={}&Sec-MS-GEC-Version={}&ConnectionId={}",
        token,
        version,
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
        .header("Cookie", format!("muid={};", hexid().to_uppercase()))
        .body(())
        .unwrap()
}

#[cfg(test)]
mod request_tests {
    use super::*;

    #[test]
    fn default_algorithm_is_v2_and_legacy_override_keeps_matching_v1_token() {
        assert_eq!(DEFAULT_GEC_VERSION, "2-143.0.3650.75");
        let v2 = sec_ms_gec_at(DEFAULT_GEC_VERSION, 1793318400).unwrap();
        let v1 = sec_ms_gec_at("1-143.0.3650.75", 1793318400).unwrap();
        assert_eq!(v2.len(), 81);
        assert_eq!(v1.len(), 64);
        assert!(!v1.contains('-'));
        assert_ne!(v2.split_once('-').unwrap().1, v1);
        assert!(sec_ms_gec_at("3-143.0.3650.75", 1793318400).is_err());
    }
}

// 可选观测，全部用单调时钟；未到达的阶段输出 -，不参与失败判定。
#[derive(Default)]
struct Timing {
    enabled: bool,
    tcp_ms: Option<u128>,
    tls_ws_ms: Option<u128>,
    first_audio_ms: Option<u128>,
    turn_end_ms: Option<u128>,
}

impl Timing {
    fn start(&self) -> Option<Instant> {
        if self.enabled { Some(Instant::now()) } else { None }
    }

    fn elapsed(start: Option<Instant>) -> Option<u128> {
        start.map(|t| t.elapsed().as_millis())
    }

    fn line(&self) -> Option<String> {
        if !self.enabled { return None; }
        let value = |v: Option<u128>| v.map(|n| n.to_string()).unwrap_or_else(|| "-".into());
        Some(format!("[T] tcp_ms={} tls_ws_ms={} first_audio_ms={} turn_end_ms={}",
            value(self.tcp_ms), value(self.tls_ws_ms),
            value(self.first_audio_ms), value(self.turn_end_ms)))
    }

    fn report(&self) {
        if let Some(line) = self.line() { eprintln!("{line}"); }
    }
}

#[cfg(test)]
mod timing_tests {
    use super::*;

    #[test]
    fn timing_is_opt_in_and_missing_stages_are_not_zero() {
        assert_eq!(Timing::default().line(), None);
        assert!(Timing::default().start().is_none());
        let timing = Timing { enabled: true, tcp_ms: Some(12), tls_ws_ms: Some(34),
            first_audio_ms: Some(56), ..Timing::default() };
        let line = timing.line().unwrap();
        assert_eq!(line, "[T] tcp_ms=12 tls_ws_ms=34 first_audio_ms=56 turn_end_ms=-");
        assert!(!line.contains("[!]"));
    }
}

// 阻塞建链：TCP（带超时）→ rustls TLS → WebSocket 升级握手。
fn connect(timing: &mut Timing) -> tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<TcpStream>> {
    let tcp_start = timing.start();
    let tcp = TcpStream::connect((HOST, 443)).expect("tcp connect");
    timing.tcp_ms = Timing::elapsed(tcp_start);
    tcp.set_read_timeout(Some(Duration::from_secs(20))).ok();
    tcp.set_write_timeout(Some(Duration::from_secs(20))).ok();
    let tls_start = timing.start();
    let (ws, resp) = tungstenite::client_tls(build_request(), tcp).unwrap_or_else(|e| {
        eprintln!("[!] ws handshake failed: {e}");
        std::process::exit(2);
    });
    timing.tls_ws_ms = Timing::elapsed(tls_start);
    eprintln!("[+] handshake OK, HTTP {}", resp.status());
    ws
}

fn speech_messages(text: &str, voice: &str) -> (String, String) {
    let date = chrono::Utc::now()
        .format("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)")
        .to_string();
    let fmt = env_or("ETTSC_FORMAT", DEFAULT_FORMAT);
    let cfg = format!(
        "X-Timestamp:{date}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n{{\"context\":{{\"synthesis\":{{\"audio\":{{\"metadataoptions\":{{\"sentenceBoundaryEnabled\":\"false\",\"wordBoundaryEnabled\":\"false\"}},\"outputFormat\":\"{fmt}\"}}}}}}}}"
    );
    let ssml = format!(
        "X-RequestId:{}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:{date}Z\r\nPath:ssml\r\n\r\n<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'><voice name='{voice}'><prosody pitch='+0Hz' rate='+0%' volume='+0%'>{text}</prosody></voice></speak>",
        hexid()
    );
    (cfg, ssml)
}

fn main() {
    let enabled = match env_or("ETTSC_TIMING", "0").as_str() {
        "1" => true,
        "0" => false,
        _ => { eprintln!("[T-CONFIG] ETTSC_TIMING 非法，使用 0"); false }
    };
    let mut timing = Timing { enabled, ..Timing::default() };
    let a: Vec<String> = std::env::args().collect();

    if a.get(1).map(|s| s == "serve").unwrap_or(false) {
        let Some(dir) = a.get(2) else {
            eprintln!("[!] serve requires a private directory");
            std::process::exit(2);
        };
        let result = persistent::run(std::path::Path::new(dir));
        let status = if result.is_ok() { b"0" } else { b"1" };
        let _ = std::fs::write(std::path::Path::new(dir).join("exited"), status);
        if result.is_err() { std::process::exit(2); }
        return;
    }

    if a.get(1).map(|s| s == "prewarm").unwrap_or(false) {
        let Some(dir) = a.get(2) else {
            eprintln!("[!] prewarm requires a private job directory");
            std::process::exit(2);
        };
        let voice = a.get(3).map(String::as_str).unwrap_or("zh-CN-YunjianNeural");
        let rc = prewarm::run(std::path::Path::new(dir), voice, &mut timing);
        timing.report();
        let status = if rc.is_ok() { b"0" } else { b"1" };
        if std::fs::write(std::path::Path::new(dir).join("done"), status).is_err() {
            std::process::exit(2);
        }
        if rc.is_err() { std::process::exit(2); }
        return;
    }

    if a.get(1).map(|s| s == "probe").unwrap_or(false) {
        eprintln!("[*] probe ...");
        let mut ws = connect(&mut timing);
        let _ = ws.close(None);
        timing.report();
        return;
    }

    let text = a.get(1).cloned().unwrap_or_else(|| "你好，这是音箱端直连 EdgeTTS 测试。".into());
    let out = a.get(2).cloned().unwrap_or_else(|| "/tmp/edgetts.mp3".into());
    let voice = a.get(3).cloned().unwrap_or_else(|| "zh-CN-YunjianNeural".into());

    if let Some(live) = std::env::var_os("ETTSC_STREAM_PCM").filter(|path| !path.is_empty()) {
        let rc = prewarm::connect(&mut timing).and_then(|mut ws|
            prewarm::receive_audio(&mut ws, None, &voice, &text, &mut timing,
                                   Some(std::path::Path::new(&live))));
        timing.report();
        if rc.is_err() {
            eprintln!("[!] incremental PCM synthesis failed");
            std::process::exit(3);
        }
        return;
    }

    eprintln!("[*] connecting ...");
    let mut ws = connect(&mut timing);

    let (cfg, ssml) = speech_messages(&text, &voice);
    ws.send(Message::Text(cfg)).unwrap();
    ws.send(Message::Text(ssml)).unwrap();
    eprintln!("[*] sent config+ssml, receiving ...");

    let receive_start = timing.start();
    let mut audio: Vec<u8> = Vec::new();
    let mut frames = 0u32;
    loop {
        match ws.read() {
            Ok(Message::Text(t)) => {
                if t.contains("Path:turn.end") {
                    timing.turn_end_ms = Timing::elapsed(receive_start);
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
                    if start < b.len() && timing.first_audio_ms.is_none() {
                        timing.first_audio_ms = Timing::elapsed(receive_start);
                    }
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
    timing.report();
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
    decode_mp3_checked(mp3, gain).0
}

fn pcm_gain(sample: i16, gain: f32) -> i16 {
    if (gain - 1.0).abs() > 0.001 {
        (sample as f32 * gain).round().clamp(-32768.0, 32767.0) as i16
    } else {
        sample
    }
}

fn decode_mp3_checked(mp3: &[u8], gain: f32) -> (Vec<u8>, bool) {
    let mut dec = minimp3::Decoder::new(mp3);
    let mut out: Vec<u8> = Vec::new();
    let mut peak: i32 = 0;
    let mut complete = true;
    loop {
        match dec.next_frame() {
            Ok(minimp3::Frame { data, .. }) => {
                for s in data {
                    let a = (s as i32).abs();
                    if a > peak {
                        peak = a;
                    }
                    out.extend_from_slice(&pcm_gain(s, gain).to_le_bytes());
                }
            }
            Err(minimp3::Error::Eof) => break,
            Err(e) => {
                eprintln!("[!] mp3 decode err: {e:?}");
                complete = false;
                break;
            }
        }
    }
    let headroom = if peak > 0 { 32767.0 / peak as f32 } else { 0.0 };
    eprintln!("[*] pcm peak={peak}/32767 ({:.0}%), 无削顶最大增益≈{headroom:.2}x", peak as f32 / 32767.0 * 100.0);
    (out, complete)
}
