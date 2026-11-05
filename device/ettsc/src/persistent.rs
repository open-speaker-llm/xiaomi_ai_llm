//! Private, atomically published job directories carry text/voice and PCM.
//! One blocking WebSocket is reused; reconnect once if a turn fails before publish.
use super::{env_or, prewarm, Timing};
use std::fs;
use std::io::Read;
use std::path::Path;
use std::time::{Duration, Instant};
use tungstenite::{stream::MaybeTlsStream, WebSocket};
use std::net::TcpStream;

type Socket = WebSocket<MaybeTlsStream<TcpStream>>;
const MAX_TEXT: u64 = 65536;

fn job_id(value: &str) -> bool {
    value.starts_with("job.") && value.len() <= 40 && value.len() > 4 &&
        value[4..].bytes().all(|c| c.is_ascii_alphanumeric())
}

fn read_text(path: &Path, max: u64) -> Result<String, ()> {
    let mut text = String::new();
    fs::File::open(path).map_err(|_| ())?.take(max + 1).read_to_string(&mut text).map_err(|_| ())?;
    if text.is_empty() || text.len() as u64 > max { return Err(()); }
    Ok(text)
}

fn next_job(dir: &Path, idle: Duration) -> Result<Option<String>, ()> {
    let deadline = Instant::now() + idle;
    loop {
        for entry in fs::read_dir(dir).map_err(|_| ())? {
            let entry = entry.map_err(|_| ())?;
            let Some(id) = entry.file_name().to_str().map(str::to_owned) else { continue; };
            if job_id(&id) && entry.path().join("queued").is_file() {
                fs::remove_file(entry.path().join("queued")).map_err(|_| ())?;
                return Ok(Some(id));
            }
        }
        if Instant::now() >= deadline { return Ok(None); }
        std::thread::sleep(Duration::from_millis(20));
    }
}

fn turn<F>(dir: &Path, socket: &mut Option<Socket>, timing: &mut Timing, connect: &mut F) -> (bool, usize)
where F: FnMut(&mut Timing) -> Result<Socket, ()> {
    let text = read_text(&dir.join("request"), MAX_TEXT);
    let voice = read_text(&dir.join("voice"), 256);
    let (Ok(text), Ok(voice)) = (text, voice) else { return (false, 0); };
    let mut reconnects = 0;
    for _ in 0..2 {
        if dir.join("cancel").exists() { *socket = None; break; }
        let _ = fs::remove_file(dir.join("audio.part"));
        let _ = fs::remove_file(dir.join("audio.pcm"));
        if socket.is_none() {
            reconnects += 1;
            *socket = connect(timing).ok();
        }
        if let Some(ws) = socket {
            if prewarm::synthesize(ws, dir, &voice, &text, timing).is_ok() {
                return (true, reconnects);
            }
        }
        *socket = None; // Never reuse a socket with an unfinished turn.
    }
    let _ = fs::remove_file(dir.join("audio.part"));
    let _ = fs::remove_file(dir.join("audio.pcm"));
    (false, reconnects)
}

pub(super) fn run(dir: &Path) -> Result<(), ()> {
    if !dir.is_dir() { return Err(()); }
    let idle = env_or("ETTSC_IDLE_SECS", "20").parse::<u64>().ok()
        .filter(|n| (1..=120).contains(n)).unwrap_or(20);
    let enabled = env_or("ETTSC_TIMING", "0") == "1";
    let mut initial = Timing { enabled, ..Timing::default() };
    let mut socket = Some(prewarm::connect(&mut initial)?);
    fs::write(dir.join("first"), b"1").map_err(|_| ())?;
    fs::write(dir.join("ready"), b"1").map_err(|_| ())?;
    loop {
        let Some(id) = next_job(dir, Duration::from_secs(idle))? else {
            socket = None;
            // A model may still be generating. Release the idle socket, but keep
            // this owned worker available to reconnect for the pending round.
            if dir.join("round_active").exists() { continue; }
            return Ok(());
        };
        let job = dir.join(&id);
        if !job.is_dir() { return Err(()); }
        let mut timing = std::mem::replace(&mut initial, Timing { enabled, ..Timing::default() });
        let reused = socket.is_some() && !dir.join("first").exists();
        let (ok, reconnects) = turn(&job, &mut socket, &mut timing, &mut prewarm::connect);
        let line = format!("{}\n[TTS] persistent reused={} reconnects={}\n",
                           timing.line().unwrap_or_default(), usize::from(reused && reconnects == 0), reconnects);
        fs::write(job.join("worker.log"), line).map_err(|_| ())?;
        // Complete all writes before the final done marker. Each job has its own
        // random directory, so timed-out output cannot satisfy a later request.
        let _ = fs::remove_file(dir.join("busy"));
        if job.join("cancel").exists() {
            let _ = fs::remove_dir_all(&job);
        } else {
            fs::write(job.join("done"), if ok { b"0" } else { b"1" }).map_err(|_| ())?;
        }
        let _ = fs::remove_file(dir.join("first"));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unpublished_jobs_are_ignored_and_idle_is_bounded() {
        let dir = std::env::temp_dir().join(format!("ettsc-queue-{}", super::super::hexid()));
        fs::create_dir(&dir).unwrap();
        let job = dir.join("job.Abc123");
        fs::create_dir(&job).unwrap();
        fs::write(job.join("request"), b"not published").unwrap();
        assert_eq!(next_job(&dir, Duration::from_millis(25)).unwrap(), None);
        fs::write(job.join("queued"), b"").unwrap();
        assert_eq!(next_job(&dir, Duration::from_secs(1)).unwrap(), Some("job.Abc123".into()));
        assert!(!job.join("queued").exists());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn multiple_turns_share_socket_and_a_closed_socket_reconnects_once() {
        use std::net::TcpListener;
        let dir = std::env::temp_dir().join(format!("ettsc-reuse-{}", super::super::hexid()));
        fs::create_dir(&dir).unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let mut expected = 0;
            for count in [2, 1] {
                let (tcp, _) = listener.accept().unwrap();
                tcp.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
                let mut ws = tungstenite::accept(tcp).unwrap();
                for _ in 0..count {
                    assert!(ws.read().unwrap().into_text().unwrap().contains("Path:speech.config"));
                    assert!(ws.read().unwrap().into_text().unwrap().contains(&format!("text-{expected}")));
                    let mut audio = vec![0, 0];
                    audio.extend_from_slice(include_bytes!("../tests/fixtures/tone-24k-mono.mp3"));
                    ws.send(tungstenite::Message::Binary(audio)).unwrap();
                    ws.send(tungstenite::Message::Text("Path:turn.end\r\n\r\n".into())).unwrap();
                    expected += 1;
                }
                let _ = ws.close(None);
            }
        });
        let mut connections = 0;
        let mut connect = |_: &mut Timing| {
            connections += 1;
            let tcp = TcpStream::connect(address).unwrap();
            tcp.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
            let (ws, _) = tungstenite::client(format!("ws://{address}"), MaybeTlsStream::Plain(tcp)).unwrap();
            Ok(ws)
        };
        let mut socket = Some(connect(&mut Timing::default()).unwrap());
        for index in 0..3 {
            let job = dir.join(format!("job.Test{index}")); fs::create_dir(&job).unwrap();
            fs::write(job.join("request"), format!("text-{index}")).unwrap();
            fs::write(job.join("voice"), "test-voice").unwrap();
            let (ok, reconnects) = turn(&job, &mut socket, &mut Timing::default(), &mut connect);
            assert!(ok);
            assert_eq!(reconnects, usize::from(index == 2));
            assert!(fs::metadata(job.join("audio.pcm")).unwrap().len() > 0);
            assert!(!job.join("audio.part").exists());
        }
        assert_eq!(connections, 2);
        server.join().unwrap();
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn canceled_and_oversized_jobs_never_connect_or_publish() {
        let dir = std::env::temp_dir().join(format!("ettsc-reject-{}", super::super::hexid()));
        fs::create_dir(&dir).unwrap();
        fs::write(dir.join("request"), vec![b'x'; MAX_TEXT as usize + 1]).unwrap();
        fs::write(dir.join("voice"), "test-voice").unwrap();
        let mut connect = |_: &mut Timing| -> Result<Socket, ()> { panic!("unexpected connect") };
        assert_eq!(turn(&dir, &mut None, &mut Timing::default(), &mut connect), (false, 0));
        fs::write(dir.join("request"), "valid").unwrap();
        fs::write(dir.join("cancel"), b"").unwrap();
        assert_eq!(turn(&dir, &mut None, &mut Timing::default(), &mut connect), (false, 0));
        assert!(!dir.join("audio.pcm").exists());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn ids_cannot_escape_private_directory() {
        assert!(job_id("job.Abc123"));
        for id in ["../job.a", "job.a/../b", "job.", "job.a\njob.b", "job.中文"] {
            assert!(!job_id(id));
        }
    }
}
