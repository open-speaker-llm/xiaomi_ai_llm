//! Incremental decoding of the existing Edge 24 kHz mono CBR MP3 format.
use std::fs::{File, OpenOptions};
use std::io::{Cursor, Write};
use std::path::{Path, PathBuf};

pub(super) struct PcmStream {
    decoder: minimp3::Decoder<Cursor<Vec<u8>>>,
    pending: Vec<u8>,
    file: File,
    first_pcm: PathBuf,
    gain: f32,
    bytes: usize,
}

impl PcmStream {
    pub(super) fn open(path: &Path) -> Result<Self, ()> {
        Ok(Self {
            decoder: minimp3::Decoder::new(Cursor::new(Vec::with_capacity(145))),
            pending: Vec::new(),
            file: OpenOptions::new().create(true).append(true).open(path).map_err(|_| ())?,
            first_pcm: path.with_extension("first_pcm"),
            gain: super::env_or("ETTSC_GAIN", "1.0").parse().unwrap_or(1.0),
            bytes: 0,
        })
    }

    pub(super) fn push(&mut self, payload: &[u8]) -> Result<(), ()> {
        self.pending.extend_from_slice(payload);
        let mut consumed = 0;
        let mut pcm = Vec::new();
        while self.pending.len() - consumed >= 4 {
            let frame = &self.pending[consumed..];
            // MPEG-2 Layer III, 48 kbps, 24 kHz, mono: 144 bytes + optional padding.
            if frame[0] != 0xff || frame[1] & 0xfe != 0xf2 ||
                frame[2] & 0xfc != 0x64 || frame[3] & 0xc0 != 0xc0 {
                return Err(());
            }
            let len = 144 + usize::from(frame[2] & 2 != 0);
            if frame.len() < len { break; }
            let input = self.decoder.reader_mut();
            input.set_position(0);
            input.get_mut().clear();
            input.get_mut().extend_from_slice(&frame[..len]);
            let frame = self.decoder.next_frame().map_err(|_| ())?;
            for sample in frame.data {
                pcm.extend_from_slice(&super::pcm_gain(sample, self.gain).to_le_bytes());
            }
            consumed += len;
        }
        self.pending.drain(..consumed);
        self.file.write_all(&pcm).map_err(|_| ())?;
        if self.bytes == 0 && !pcm.is_empty() {
            if let Some(ms) = std::fs::read_to_string("/proc/uptime").ok()
                .and_then(|s| s.split_whitespace().next()?.parse::<f64>().ok())
                .map(|seconds| (seconds * 1000.0) as u64)
            {
                let _ = std::fs::write(&self.first_pcm, ms.to_string());
            }
        }
        self.bytes += pcm.len();
        Ok(())
    }

    pub(super) fn finish(self) -> Result<(), ()> {
        if self.bytes > 0 && self.pending.is_empty() { Ok(()) } else { Err(()) }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn split_packets_publish_pcm_early_and_match_buffered_decoder() {
        let path = std::env::temp_dir().join(format!("ettsc-live-{}", super::super::hexid()));
        let input = include_bytes!("../tests/fixtures/tone-24k-mono.mp3");
        let mut stream = PcmStream::open(&path).unwrap();
        stream.push(&input[..143]).unwrap();
        assert_eq!(fs::metadata(&path).unwrap().len(), 0);
        stream.push(&input[143..145]).unwrap();
        assert_eq!(fs::metadata(&path).unwrap().len(), 1152);
        for packet in input[145..].chunks(73) {
            stream.push(packet).unwrap();
        }
        stream.finish().unwrap();
        assert_eq!(fs::read(&path).unwrap(), super::super::decode_mp3_checked(input, 1.0).0);
        let _ = fs::remove_file(path.with_extension("first_pcm"));
        fs::remove_file(path).unwrap();
    }
}
