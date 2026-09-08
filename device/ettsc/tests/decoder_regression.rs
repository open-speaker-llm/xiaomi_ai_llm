use minimp3::{Decoder, Error};
use sha2::{Digest, Sha256};
use std::io::{self, Read};

const TONE: &[u8] = include_bytes!("fixtures/tone-24k-mono.mp3");

fn decode(reader: impl Read) -> (usize, Vec<i16>) {
    let mut decoder = Decoder::new(reader);
    let mut frames = 0;
    let mut pcm = Vec::new();
    loop {
        match decoder.next_frame() {
            Ok(frame) => {
                assert_eq!(frame.sample_rate, 24_000);
                assert_eq!(frame.channels, 1);
                pcm.extend(frame.data);
                frames += 1;
            }
            Err(Error::Eof) => break,
            Err(e) => panic!("unexpected decode error: {e}"),
        }
        assert!(frames < 10_000, "decoder did not reach EOF");
    }
    (frames, pcm)
}

#[test]
fn vulnerable_buffer_is_absent_from_lockfile() {
    let lock = include_str!("../Cargo.lock");
    for package in ["slice-ring-buffer", "slice-deque"] {
        assert!(
            !lock.contains(&format!("name = \"{package}\"")),
            "{package} must not re-enter the MP3 dependency tree (RUSTSEC-2025-0044)"
        );
    }
}

#[test]
fn pcm_matches_upstream_across_many_refills() {
    // Much larger than the decoder's buffer, exercising repeated front removal
    // and refill. The fixture contains synthetic audio, no user recording.
    let input = TONE.repeat(32);
    let (frames, pcm) = decode(input.as_slice());
    let bytes: Vec<u8> = pcm.iter().flat_map(|s| s.to_le_bytes()).collect();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    assert_eq!(frames, 1408);
    assert_eq!(pcm.len(), 811_008);
    // Recorded before the patch using the locked upstream minimp3 0.5.2.
    // Other CPU implementations may round individual samples differently.
    if cfg!(all(target_arch = "aarch64", target_os = "macos")) {
        assert_eq!(
            digest,
            "7332e81ec31e2ca5eb96ea8e3e28bf3e24f622b48994f3c4fcb23824838751f1"
        );
    }
}

struct Chunked<'a>(&'a [u8]);

impl Read for Chunked<'_> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        let len = out.len().min(4096);
        self.0.read(&mut out[..len])
    }
}

#[test]
fn short_reads_preserve_pcm() {
    let input = TONE.repeat(16);
    assert_eq!(decode(Chunked(&input)), decode(input.as_slice()));
}

#[test]
fn unaligned_stream_preserves_frames_across_buffer_wrap() {
    let input = TONE.repeat(32);
    // A non-frame prefix shifts MP3 frames relative to the ring allocation.
    // An implementation passing only the first VecDeque slice can then split
    // a frame at the wrap boundary and silently lose audio.
    let mut padded = vec![0x55; 13];
    padded.extend_from_slice(&input);
    assert!(
        decode(padded.as_slice()) == decode(input.as_slice()),
        "unaligned frame at the ring boundary changed PCM output"
    );
}

#[test]
fn empty_and_invalid_input_reach_eof() {
    assert_eq!(decode(&[][..]), (0, vec![]));
    assert_eq!(decode(vec![0x55; 100_000].as_slice()), (0, vec![]));
}

#[test]
fn truncated_last_frame_preserves_decoded_prefix() {
    let (_, full) = decode(TONE);
    let (_, partial) = decode(&TONE[..TONE.len() - 100]);
    assert!(!partial.is_empty());
    assert!(partial.len() < full.len());
    assert_eq!(partial, full[..partial.len()]);
}

#[test]
fn reader_errors_are_propagated() {
    struct Broken;
    impl Read for Broken {
        fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
            Err(io::Error::new(io::ErrorKind::PermissionDenied, "test"))
        }
    }
    assert!(
        matches!(Decoder::new(Broken).next_frame(), Err(Error::Io(e))
        if e.kind() == io::ErrorKind::PermissionDenied)
    );
}
