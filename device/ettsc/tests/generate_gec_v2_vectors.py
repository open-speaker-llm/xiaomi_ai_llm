#!/usr/bin/env python3
"""Reproduce GEC v2 fixtures with the pinned Python upstream; no network calls."""
import argparse
import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "vendor/edge-tts"
COMMIT = "bd44c1d1aaebdc1db7f47456ee12431b42ec7cac"
HASHES = {
    "drm.py": "b29c37e2a0c11284adb2a1ffc04f0f231e1ba2d921494a912797218b05d64c4a",
    "constants.py": "6c987fafa0a10aad81d8d5fc3447a14f2bca2eb86b4f97296c384253d3906c94",
}
TIMESTAMPS = (0, 1, 299, 300, 301, 1700000000, 1710000000, 1728000000,
              1760000000, 1793318400, 1793318699, 1793318700, 2147483647,
              2147483648, 4102444800, 4294967295, 4294967296)
LENGTHS = (7, 8, 15, 32, 50, 55, 56, 63, 64, 65, 100, 130)


def reference():
    for name, expected in HASHES.items():
        if hashlib.sha256((UPSTREAM / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Pinned upstream changed: {name}")
    constants = ast.parse((UPSTREAM / "constants.py").read_text())
    trusted = next(ast.literal_eval(node.value) for node in constants.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "TRUSTED_CLIENT_TOKEN"
                           for target in node.targets))
    module = ast.parse((UPSTREAM / "drm.py").read_text())
    # Execute the original arithmetic functions unchanged. Their networking
    # imports and DRM class are unnecessary when timestamps are explicit.
    module.body = [node for node in module.body
                   if not isinstance(node, ast.ClassDef)
                   and not (isinstance(node, ast.ImportFrom) and node.level)
                   and not (isinstance(node, ast.Import)
                            and any(alias.name == "aiohttp" for alias in node.names))]
    namespace = {"TRUSTED_CLIENT_TOKEN": trusted}
    exec(compile(module, str(UPSTREAM / "drm.py"), "exec"), namespace)
    return namespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare without rewriting fixtures")
    args = parser.parse_args()
    upstream = reference()
    timestamps = (f"# Generated with upstream edge-tts {COMMIT} drm.py\n"
                  "# unix_seconds\tSec-MS-GEC-v2\n")
    timestamps += "".join(f"{value}\t{upstream['generate_sec_ms_gec_v2'](value)}\n"
                          for value in TIMESTAMPS)
    digests = "# data_hex\tCS64_hex\tSHA256_hex\n"
    for length in LENGTHS:
        data = bytes((i * 37 + 11) % 256 for i in range(length))
        cs64, sha256 = upstream["_token_hash"](data)
        digests += f"{data.hex()}\t{cs64}\t{sha256}\n"
    for name, expected in (("gec-v2-vectors.tsv", timestamps), ("gec-v2-digests.tsv", digests)):
        path = ROOT / "tests/fixtures" / name
        if args.check:
            if path.read_text() != expected:
                raise SystemExit(f"Upstream vector mismatch: {name}")
        else:
            path.write_text(expected)
    print(f"Verified {len(TIMESTAMPS)} timestamp and {len(LENGTHS)} digest vectors against {COMMIT}")


if __name__ == "__main__":
    main()
