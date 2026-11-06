#!/usr/bin/env python3
"""Compare the RMS of two 24 kHz, mono, signed 16-bit little-endian PCM files."""

import argparse
import math
from pathlib import Path
import struct


def rms(data: bytes) -> float:
    if not data or len(data) % 2:
        raise ValueError("PCM must contain complete 16-bit samples")
    return math.sqrt(sum(sample * sample for (sample,) in struct.iter_unpack("<h", data))
                     / (len(data) // 2))


def difference_db(cue: float, reference: float) -> float:
    if cue <= 0 or reference <= 0:
        raise ValueError("Both inputs must contain audible samples")
    return 20 * math.log10(cue / reference)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cue", type=Path)
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    try:
        cue, reference = rms(args.cue.read_bytes()), rms(args.reference.read_bytes())
        delta = difference_db(cue, reference)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"cue_rms={cue:.2f} reference_rms={reference:.2f} difference_db={delta:+.2f}")
    return int(abs(delta) > 3)


if __name__ == "__main__":
    raise SystemExit(main())
