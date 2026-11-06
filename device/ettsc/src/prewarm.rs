//! One connection, one synthesis turn. No background synthesis or multi-turn reuse.
use super::{decode_mp3_checked, env_or, speech_messages, Timing, HOST};
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::Path;
use std::time::{Duration, Instant};
use tungstenite::{stream::MaybeTlsStream, Message, WebSocket};

const IDLE: Duration = Duration::from_secs(20);
const MAX_TEXT: usize = 65536;
const MAX_AUDIO: usize = 16 * 1024 * 1024;

// Only the experimental mode changes connection timeouts. Errors are deliberately
// static: HTTP errors can contain cookies or authentication query parameters.
pub(super) fn connect(timing: &mut Timing) -> Result<WebSocket<MaybeTlsStream<TcpStream>>, ()> {
    let tcp_start = timing.start();
    let deadline = Instant::now() + Duration::from_secs(5);
    let addresses = (HOST, 443).to_socket_addrs().map_err(|_| ())?;
    let mut stream = None;
    for address in addresses {
        let remaining = deadline.checked_duration_since(Instant::now()).ok_or(())?;
        if let Ok(tcp) = TcpStream::connect_timeout(&address, remaining) {
            stream = Some(tcp);
            break;
        }
    }
    let tcp = stream.ok_or(())?;
    timing.tcp_ms = Timing::elapsed(tcp_start);
    tcp.set_read_timeout(Some(Duration::from_secs(5))).map_err(|_| ())?;
    tcp.set_write_timeout(Some(Duration::from_secs(5))).map_err(|_| ())?;
    let tls_start = timing.start();
    let (ws, _) = tungstenite::client_tls(super::build_request(), tcp).map_err(|_| ())?;
    timing.tls_ws_ms = Timing::elapsed(tls_start);
    Ok(ws)
}

fn request(dir: &Path, idle: Duration) -> Result<String, ()> {
    let deadline = Instant::now() + idle;
    loop {
        if dir.join("cancel").exists() { return Err(()); }
        if dir.join("request").is_file() {
            let mut input = fs::File::open(dir.join("request")).map_err(|_| ())?;
            let mut text = String::new();
            (&mut input).take((MAX_TEXT + 1) as u64).read_to_string(&mut text).map_err(|_| ())?;
            if text.is_empty() || text.len() > MAX_TEXT { return Err(()); }
            return Ok(text);
        }
        if Instant::now() >= deadline { return Err(()); }
        std::thread::sleep(Duration::from_millis(20));
    }
}

pub(super) fn receive_audio<S: Read + Write>(ws: &mut WebSocket<S>, cancel: Option<&Path>,
                              voice: &str, text: &str, timing: &mut Timing,
                              live: Option<&Path>) -> Result<Vec<u8>, ()> {
    let (config, ssml) = speech_messages(text, voice);
    let mut stream = live.map(super::stream_pcm::PcmStream::open).transpose()?;
    let mut received = 0;
    ws.send(Message::Text(config)).map_err(|_| ())?;
    ws.send(Message::Text(ssml)).map_err(|_| ())?;
    let start = timing.start();
    let mut audio = Vec::new();
    loop {
        if cancel.is_some_and(Path::exists) { return Err(()); }
        match ws.read().map_err(|_| ())? {
            Message::Text(text) if text.contains("Path:turn.end") => {
                timing.turn_end_ms = Timing::elapsed(start);
                break;
            }
            Message::Binary(bytes) => {
                if bytes.len() < 2 { return Err(()); }
                let start_of_audio = 2 + u16::from_be_bytes([bytes[0], bytes[1]]) as usize;
                let payload = bytes.get(start_of_audio..).ok_or(())?;
                received += payload.len();
                if received > MAX_AUDIO { return Err(()); }
                if !payload.is_empty() && timing.first_audio_ms.is_none() {
                    timing.first_audio_ms = Timing::elapsed(start);
                }
                if let Some(stream) = &mut stream {
                    stream.push(payload)?;
                } else {
                    audio.extend_from_slice(payload);
                }
            }
            Message::Close(_) => return Err(()),
            _ => {}
        }
    }
    if received == 0 || cancel.is_some_and(Path::exists) { return Err(()); }
    if let Some(stream) = stream { stream.finish()?; }
    Ok(audio)
}

pub(super) fn synthesize<S: Read + Write>(ws: &mut WebSocket<S>, dir: &Path, voice: &str,
                              text: &str, timing: &mut Timing) -> Result<(), ()> {
    let live = dir.join("audio.live");
    let streaming = live.is_file();
    let audio = receive_audio(ws, Some(&dir.join("cancel")), voice, text, timing,
                              streaming.then_some(live.as_path()))?;
    if streaming { return fs::rename(live, dir.join("audio.pcm")).map_err(|_| ()); }
    let gain = env_or("ETTSC_GAIN", "1.0").parse().unwrap_or(1.0);
    let (pcm, decoded) = decode_mp3_checked(&audio, gain);
    if !decoded || pcm.is_empty() || dir.join("cancel").exists() { return Err(()); }
    fs::write(dir.join("audio.part"), pcm).map_err(|_| ())?;
    fs::rename(dir.join("audio.part"), dir.join("audio.pcm")).map_err(|_| ())
}

fn connected<S: Read + Write>(mut ws: WebSocket<S>, dir: &Path, voice: &str,
                              timing: &mut Timing, idle: Duration) -> Result<(), ()> {
    fs::write(dir.join("ready"), b"1").map_err(|_| ())?;
    let text = request(dir, idle)?;
    synthesize(&mut ws, dir, voice, &text, timing)
}

pub(super) fn run(dir: &Path, voice: &str, timing: &mut Timing) -> Result<(), ()> {
    if !dir.is_dir() { return Err(()); }
    let result = connect(timing).and_then(|ws| connected(ws, dir, voice, timing, IDLE));
    if result.is_err() {
        let _ = fs::remove_file(dir.join("audio.part"));
        let _ = fs::remove_file(dir.join("audio.pcm"));
        eprintln!("[!] prewarm unavailable; use ordinary synthesis");
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::sync::mpsc;
    use std::thread;

    fn directory() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("ettsc-prewarm-{}", super::super::hexid()));
        fs::create_dir(&path).unwrap();
        path
    }

    #[test]
    fn request_is_bounded_cancelable_and_ignores_unpublished_text() {
        let dir = directory();
        fs::write(dir.join("request.part"), "not yet published").unwrap();
        assert!(request(&dir, Duration::from_millis(25)).is_err());
        fs::write(dir.join("request"), vec![b'x'; MAX_TEXT + 1]).unwrap();
        assert!(request(&dir, IDLE).is_err());
        fs::write(dir.join("request"), "valid").unwrap();
        fs::write(dir.join("cancel"), b"").unwrap();
        assert!(request(&dir, IDLE).is_err());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn live_job_publishes_before_turn_end_and_finishes_the_same_pcm() {
        let dir = directory();
        fs::write(dir.join("audio.live"), b"").unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let audio = include_bytes!("../tests/fixtures/tone-24k-mono.mp3");
        let (finish_tx, finish_rx) = mpsc::channel();
        let server = thread::spawn(move || {
            let (tcp, _) = listener.accept().unwrap();
            let mut ws = tungstenite::accept(tcp).unwrap();
            ws.read().unwrap();
            ws.read().unwrap();
            let mut packet = vec![0, 0];
            packet.extend_from_slice(&audio[..145]);
            ws.send(Message::Binary(packet)).unwrap();
            finish_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            let mut packet = vec![0, 0];
            packet.extend_from_slice(&audio[145..]);
            ws.send(Message::Binary(packet)).unwrap();
            ws.send(Message::Text("Path:turn.end".into())).unwrap();
        });
        let tcp = TcpStream::connect(address).unwrap();
        tcp.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
        let (mut ws, _) = tungstenite::client(format!("ws://{address}"), tcp).unwrap();
        let job = dir.clone();
        let worker = thread::spawn(move || {
            synthesize(&mut ws, &job, "voice", "text", &mut Timing::default())
        });
        let deadline = Instant::now() + Duration::from_secs(2);
        while fs::metadata(dir.join("audio.live")).unwrap().len() < 1152 {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(5));
        }
        assert!(!dir.join("audio.pcm").exists());
        finish_tx.send(()).unwrap();
        worker.join().unwrap().unwrap();
        server.join().unwrap();
        assert_eq!(fs::read(dir.join("audio.pcm")).unwrap(), decode_mp3_checked(audio, 1.0).0);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn held_socket_handles_exactly_one_turn_and_rejects_incomplete_audio() {
        for complete in [true, false] {
            let dir = directory();
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let address = listener.local_addr().unwrap();
            let (connected_tx, connected_rx) = mpsc::channel();
            let server = thread::spawn(move || {
                let (tcp, _) = listener.accept().unwrap();
                tcp.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
                let mut ws = tungstenite::accept(tcp).unwrap();
                connected_tx.send(()).unwrap();
                assert!(ws.read().unwrap().into_text().unwrap().contains("Path:speech.config"));
                let ssml = ws.read().unwrap().into_text().unwrap();
                assert!(ssml.contains("first sentence"));
                let mut bytes = vec![0, 0];
                bytes.extend_from_slice(include_bytes!("../tests/fixtures/tone-24k-mono.mp3"));
                ws.send(Message::Binary(bytes)).unwrap();
                if complete {
                    ws.send(Message::Text("Path:turn.end\r\n\r\n".into())).unwrap();
                } else {
                    ws.close(None).unwrap();
                }
            });
            let tcp = TcpStream::connect(address).unwrap();
            tcp.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
            let (ws, _) = tungstenite::client(format!("ws://{address}"), tcp).unwrap();
            connected_rx.recv_timeout(Duration::from_secs(2)).unwrap();
            let worker_dir = dir.clone();
            let worker = thread::spawn(move || {
                connected(ws, &worker_dir, "test-voice", &mut Timing::default(), IDLE)
            });
            let deadline = Instant::now() + Duration::from_secs(2);
            while !dir.join("ready").exists() {
                assert!(Instant::now() < deadline);
                thread::sleep(Duration::from_millis(5));
            }
            // The WebSocket is already established while no text/audio exists.
            assert!(!dir.join("audio.pcm").exists());
            fs::write(dir.join("request.part"), "first sentence").unwrap();
            fs::rename(dir.join("request.part"), dir.join("request")).unwrap();
            assert_eq!(worker.join().unwrap().is_ok(), complete);
            assert_eq!(dir.join("audio.pcm").exists(), complete);
            assert!(!dir.join("audio.part").exists());
            server.join().unwrap();
            fs::remove_dir_all(dir).unwrap();
        }
    }
}
