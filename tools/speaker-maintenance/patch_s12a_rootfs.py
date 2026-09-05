#!/usr/bin/env python3
"""Build a reviewed S12A rootfs; never connect to or flash a device.

Only the two examined ROM layouts are accepted. New ROMs need a fresh audit.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

HERE = Path(__file__).resolve().parent
PARTITION_BYTES = 32 * 1024 * 1024
SUPPORTED_ROMS = {"1.54.8", "1.76.54"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def inventory(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            rel = str(path.relative_to(root))
            info = path.lstat()
            if path.is_symlink():
                result[rel] = {"link": os.readlink(path)}
            elif path.is_file():
                result[rel] = {"sha256": sha256(path), "mode": stat.S_IMODE(info.st_mode)}
            else:
                result[rel] = {"mode": stat.S_IMODE(info.st_mode)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--rom", required=True, choices=sorted(SUPPORTED_ROMS))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    source = args.input.resolve()
    if sha256(source) != args.input_sha256:
        raise SystemExit("Input SHA256 mismatch")
    listing = run(["unsquashfs", "-lln", str(source)])
    # The examined images are entirely owned by root. Refuse unknown ownership.
    for line in listing.splitlines():
        if re.match(r"^[bcdlps-][rwxstST-]{9}\s", line) and line.split()[1] != "0/0":
            raise SystemExit("Unexpected non-root image ownership")
    devices = [line for line in listing.splitlines() if re.match(r"^[bc][rwxstST-]{9}\s", line)]
    allowed_devices = {"dev/console", "dev/null", "dev/ptmx"}
    for line in devices:
        if line.split("squashfs-root/", 1)[-1] not in allowed_devices:
            raise SystemExit("Unexpected device node: " + line)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    root = out / "root"
    extracted = subprocess.run(["unsquashfs", "-no-progress", "-d", str(root), str(source)],
                               capture_output=True, text=True)
    (out / "extract.log").write_text(extracted.stdout + extracted.stderr)
    errors = [line for line in extracted.stderr.splitlines()
              if not ("could not create character device" in line and "not superuser" in line)]
    if errors or extracted.returncode not in (0, 2):
        raise SystemExit("Extraction failed; inspect extract.log")
    version = (root / "usr/share/mico/version").read_text()
    if not re.search(r"option\s+HARDWARE\s+['\"]S12A['\"]", version):
        raise SystemExit("Not a verified S12A image")
    if not re.search(r"option\s+ROM\s+['\"]" + re.escape(args.rom) + r"['\"]", version):
        raise SystemExit("ROM does not match the reviewed input")
    before = inventory(root)
    # Patch standard native entry points, not only the scheduled check.
    originals = root / "usr/lib/owner-maintenance"
    originals.mkdir(parents=True, exist_ok=False)
    for name in ("ota", "flash.sh"):
        target = root / "bin" / name
        if not target.is_file() or target.is_symlink() or not target.read_bytes().startswith(b"#!/bin/sh"):
            raise SystemExit("Unexpected native updater: " + name)
        saved = originals / (name + ".original")
        shutil.copyfile(target, saved)
        saved.chmod(0o600)
        shutil.copyfile(HERE / "ota-blocked.sh", target)
        target.chmod(0o755)
    cron = root / "etc/crontabs/root"
    cron_lines = cron.read_text().splitlines()
    active = [line for line in cron_lines if not line.lstrip().startswith("#") and "/bin/ota " in line]
    if len(active) != 1:
        raise SystemExit("Unexpected OTA cron layout")
    cron.write_text("\n".join("# owner-maintenance disabled: " + line if line in active else line
                              for line in cron_lines) + "\n")
    hook = root / "etc/init.d/sshen"
    shutil.copyfile(HERE / "sshen", hook)
    hook.chmod(0o755)
    link = root / "etc/rc.d/S45sshen"
    if link.is_symlink():
        if os.readlink(link) != "../init.d/sshen":
            raise SystemExit("Unexpected existing sshen symlink")
    elif link.exists():
        raise SystemExit("Unexpected sshen startup entry")
    else:
        link.symlink_to("../init.d/sshen")
    keys = root / "etc/dropbear/authorized_keys"
    if not keys.is_file() or keys.is_symlink():
        raise SystemExit("Unexpected authorized_keys mount target")
    config = root / "etc/config/dropbear"
    contents = config.read_text()
    for setting in ("PasswordAuth", "RootPasswordAuth"):
        contents, count = re.subn(r"(option\s+" + setting + r"\s+)['\"][01]['\"]", r"\g<1>'0'", contents)
        if count != 1:
            raise SystemExit("Unexpected Dropbear authentication config")
    config.write_text(contents)
    for script in (hook, root / "bin/ota", root / "bin/flash.sh"):
        run(["sh", "-n", str(script)])
    after = inventory(root)
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    allowed = {"bin/ota", "bin/flash.sh", "etc/crontabs/root", "etc/init.d/sshen", "etc/rc.d/S45sshen",
               "etc/config/dropbear", "usr/lib/owner-maintenance", "usr/lib/owner-maintenance/ota.original",
               "usr/lib/owner-maintenance/flash.sh.original"}
    if set(changed) - allowed:
        raise SystemExit("Unexpected changes: " + repr(set(changed) - allowed))
    pseudo = out / "devices.txt"
    pseudo.write_text("/dev/console c 0600 0 0 5 1\n/dev/null c 0666 0 0 1 3\n/dev/ptmx c 0666 0 0 5 2\n")
    image = out / "rootfs.squashfs"
    pack_log = run(["mksquashfs", str(root), str(image), "-comp", "xz", "-b", "131072",
                    "-no-xattrs", "-all-root", "-pf", str(pseudo), "-noappend", "-no-progress"])
    (out / "pack.log").write_text(pack_log)
    if image.stat().st_size > PARTITION_BYTES:
        raise SystemExit("Image exceeds the verified logical partition capacity")
    padded = out / "rootfs-padded.img"
    shutil.copyfile(image, padded)
    with padded.open("ab") as stream:
        stream.write(b"\0" * (PARTITION_BYTES - padded.stat().st_size))
    with gzip.open(out / "rootfs-padded.img.gz", "wb") as stream:
        stream.write(padded.read_bytes())
    # Verify the packed content, symlinks and permissions against the staged tree.
    verify = out / "verify"
    result = subprocess.run(["unsquashfs", "-no-progress", "-d", str(verify), str(padded)],
                            capture_output=True, text=True)
    errors = [line for line in result.stderr.splitlines()
              if not ("could not create character device" in line and "not superuser" in line)]
    if errors or result.returncode not in (0, 2) or inventory(verify) != after:
        raise SystemExit("Packed image content verification failed")
    verified_listing = run(["unsquashfs", "-lln", str(padded)])
    for device in allowed_devices:
        if not any(line.startswith("c") and line.endswith("squashfs-root/" + device)
                   for line in verified_listing.splitlines()):
            raise SystemExit("Packed image is missing a required device node")
    manifest = {"policy": "owner-maintenance-v1", "hardware": "S12A", "rom": args.rom,
                "input_sha256": args.input_sha256, "changed_paths": changed,
                "output_bytes": padded.stat().st_size, "output_sha256": sha256(padded),
                "gzip_sha256": sha256(out / "rootfs-padded.img.gz"),
                "verified_content": True, "flashed": False}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
