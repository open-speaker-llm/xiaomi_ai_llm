#!/usr/bin/env python3
"""Embed the native web module into the single-file client; --check is read-only."""
import embed_native_protocol as embed

if __name__ == "__main__":
    embed.SOURCE = embed.ROOT / "device/lib/native_web.sh"
    embed.BEGIN = "# BEGIN GENERATED NATIVE WEB"
    embed.END = "# END GENERATED NATIVE WEB"
    raise SystemExit(embed.main())
