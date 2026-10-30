#!/usr/bin/env python3
"""Embed the pure shell protocol module; --check never writes the client."""
import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "device/lib/native_protocol.sh"
TARGET = ROOT / "device/native_first_client.sh"
BEGIN = "# BEGIN GENERATED NATIVE PROTOCOL"
END = "# END GENERATED NATIVE PROTOCOL"


def rendered_client(client: str, source: str) -> str:
    start = BEGIN + "\n"
    finish = END + "\n"
    if client.count(start) != 1 or client.count(finish) != 1:
        raise ValueError("native protocol markers must each occur exactly once")
    before, region = client.split(start, 1)
    if finish not in region:
        raise ValueError("native protocol markers are out of order")
    _, after = region.split(finish, 1)
    return before + start + source.rstrip("\n") + "\n" + finish + after


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the embedded protocol is stale")
    args = parser.parse_args(argv)
    try:
        original = TARGET.read_bytes().decode("utf-8")
        source = SOURCE.read_bytes().decode("utf-8")
        rendered = rendered_client(original, source)
        if rendered == original:
            print("Native protocol embed is current.")
            return 0
        if args.check:
            print("Native protocol embed is stale; run python3 scripts/embed_native_protocol.py", file=sys.stderr)
            return 1
        # Preserve all bytes outside the marked region and the executable mode.
        # Refuse an observed concurrent edit instead of overwriting its changes.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=TARGET.parent,
                                         prefix=".native-protocol-", delete=False) as output:
            pending = Path(output.name)
            output.write(rendered)
        try:
            os.chmod(pending, TARGET.stat().st_mode & 0o777)
            if TARGET.read_bytes().decode("utf-8") != original or SOURCE.read_bytes().decode("utf-8") != source:
                raise ValueError("source changed during embedding; retry after the edit finishes")
            os.replace(pending, TARGET)
        finally:
            pending.unlink(missing_ok=True)
        print("Updated only the native protocol marker region.")
        return 0
    except (OSError, ValueError) as error:
        print(f"Native protocol embed failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
