#!/usr/bin/env python3
"""从已校验的本机输入构建候选整包；成功校验后发布到新的或空的目录。"""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/speaker-maintenance"))
import native_endpoint_release as release


def source_record():
    try:
        revision = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        status = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=normal"],
                                capture_output=True, text=True, check=True).stdout
        return {"revision": revision, "dirty": bool(status)}
    except (OSError, subprocess.CalledProcessError):
        return {"revision": None, "dirty": None}


def ensure_empty_output(output: Path):
    if os.path.lexists(output):
        if not stat.S_ISDIR(output.lstat().st_mode) or any(output.iterdir()):
            raise ValueError("输出必须为新的或空的实际目录；不覆盖已有包、半成品或符号链接。")


def validate_inputs(assets: Path, header: Path):
    hashes = release.parse_manifest(release.read_regular(assets / "runtime.sha256", release.MAX_JSON_BYTES), release.ASSETS)
    for name, expected in hashes.items():
        if release.digest(release.read_regular(assets / name)) != expected:
            raise ValueError("运行库输入与提供的摘要清单不符。")
    if release.digest(release.read_regular(header / "c-api-1.10.36.h")) != release.HEADER_SHA256:
        raise ValueError("sherpa-onnx 头文件不符合固定版本摘要。")
    return hashes


def check_protocol_embedding():
    checked = subprocess.run([sys.executable, str(ROOT / "scripts/embed_native_protocol.py"), "--check"],
                             capture_output=True, text=True)
    if checked.returncode:
        raise ValueError("协议模块与客户端产物不一致或无法检查；先运行 python3 scripts/embed_native_protocol.py，再重新构建。")


def write_manifest(folder: Path, names):
    return release.manifest_bytes({name: release.digest(release.read_regular(folder / name)) for name in names})


def compile_payload(assets: Path, header: Path, output: Path):
    stage = output / "runtime"
    model, wake = stage / "xiaomi_neural_shadow", stage / "xiaomi_native_wake_probe"
    model.mkdir(parents=True)
    wake.mkdir()
    for name in sorted(release.ASSETS):
        shutil.copy2(assets / name, model / name)
    src, build = ROOT / "device/endpoint_probe", output / "build"
    subprocess.run(["sh", str(src / "build_native_wake.sh"), str(build)], check=True)
    subprocess.run(["sh", str(src / "build_neural_bench.sh"), str(header), str(build)], check=True)
    for name in ("native_wake_pool", "native_resident_session"):
        shutil.copy2(build / name, wake / name)
    shutil.copy2(build / "neural_pool", model / "neural_pool")
    shutil.copy2(src / "run_neural_pool.sh", model / "run_neural_pool.sh")
    (model / "runtime.sha256").write_bytes(write_manifest(model, release.MODEL_FILES))
    (stage / "runtime-files.sha256").write_bytes(write_manifest(stage, release.RUNTIME_FILES))
    with (output / "runtime.tar.gz").open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name in sorted(release.ARCHIVE_FILES):
                path = stage / name
                info = archive.gettarinfo(str(path), arcname=name)
                info.mtime = info.uid = info.gid = 0
                info.uname = info.gname = ""
                with path.open("rb") as data:
                    archive.addfile(info, data)
    shutil.copy2(build / "native_wake_probe.so", output / "native_asr.so")
    shutil.copy2(ROOT / "device/native_first_client.sh", output / "native_first_client.sh")
    shutil.copy2(ROOT / "device/native_endpoint/manager.sh", output / "manager.sh")
    subprocess.run(["zig", "cc", "-target", "arm-linux-gnueabihf.2.25", "-Os", "-Wall", "-Wextra", "-Werror",
                    str(ROOT / "device/native_endpoint/lifecycle.c"), "-o", str(output / "lifecycle")], check=True)
    (output / "package.sha256").write_bytes(write_manifest(output, release.PAYLOADS))


def build_package(assets: Path, header: Path, output: Path):
    # Resolve parents only: resolving the final component would follow an output symlink.
    output = output.parent.resolve(strict=True) / output.name
    ensure_empty_output(output)
    check_protocol_embedding()
    hashes = validate_inputs(assets, header)
    source = source_record()
    stage = Path(tempfile.mkdtemp(prefix=".endpoint-build-", dir=output.parent))
    try:
        compile_payload(assets.resolve(), header.resolve(), stage)
        checked = release.validate_package(stage)
        if checked["runtime"]["assets"] != hashes:
            raise ValueError("输入资产在构建期间发生变化，候选包未发布。")
        if release.digest(release.read_regular(header / "c-api-1.10.36.h")) != release.HEADER_SHA256:
            raise ValueError("头文件在构建期间发生变化，候选包未发布。")
        metadata = release.make_metadata(checked["package_manifest_sha256"], checked["runtime"], source)
        (stage / "release.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        release.validate_package(stage)
        ensure_empty_output(output)
        os.replace(stage, output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return output, checked["payload_bytes"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output, size = build_package(args.assets, args.header, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("候选包未发布：" + (str(exc) if isinstance(exc, ValueError) else "输入、构建命令或输出目录操作失败。"), file=sys.stderr)
        return 1
    print("PACKAGE_BYTES", size)
    print(output / "package.sha256")
    print(output / "release.json")
    print("候选包已完成本机包体校验；ARM 执行、固件兼容与真人验收均未完成，不允许据此部署。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
