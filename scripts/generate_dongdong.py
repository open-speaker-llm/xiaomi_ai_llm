#!/usr/bin/env python3
"""Generate the S28c route cue as 24 kHz mono S16_LE WAV and raw PCM."""
import io
import math
import struct
import wave
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "asset/route-beep"
NAME = "dongdong_523"
RATE = 24000
TONE_SAMPLES = RATE * 750 // 1000
SECOND_START = RATE * 550 // 1000
ATTACK_SAMPLES = RATE * 18 // 1000
FADE_SAMPLES = RATE * 60 // 1000
HARMONICS = ((1, 1.0, 1.0), (2, 0.22, 0.5), (3, 0.06, 0.35))


def dongdong_pcm():
    tone = []
    for frame in range(TONE_SAMPLES):
        time = frame / RATE
        attack = math.sin(math.pi / 2 * min(1, frame / ATTACK_SAMPLES))
        fade = min(1, (TONE_SAMPLES - 1 - frame) / FADE_SAMPLES)
        phase = math.tau * 523 * time
        partials = sum(amplitude * math.exp(-time / (0.28 * decay)) * math.sin(harmonic * phase)
                       for harmonic, amplitude, decay in HARMONICS)
        tone.append(attack * fade * partials)

    cue = tone + [0.0] * SECOND_START
    for frame, sample in enumerate(tone, start=SECOND_START):
        cue[frame] += sample

    gain = 32767 * 10 ** (-1 / 20) / max(map(abs, cue))
    return struct.pack(f"<{len(cue)}h", *(round(sample * gain) for sample in cue))


def dongdong_wav(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    return output.getvalue()


if __name__ == "__main__":
    pcm = dongdong_pcm()
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / f"{NAME}.pcm").write_bytes(pcm)
    (ASSETS / f"{NAME}.wav").write_bytes(dongdong_wav(pcm))
