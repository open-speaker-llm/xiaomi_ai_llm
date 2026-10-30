"""Offline endpoint release contract. Never extracts archives or executes payloads."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import tarfile
import zlib


PAYLOADS = frozenset({"runtime.tar.gz", "native_asr.so", "native_first_client.sh", "manager.sh", "lifecycle"})
ASSETS = frozenset({"ld-linux-armhf.so.3", "libc.so.6", "libdl.so.2", "libm.so.6",
                    "libonnxruntime.so", "libpthread.so.0", "librt.so.1",
                    "libsherpa-onnx-c-api.so", "libstdc++.so.6", "silero_vad_v5.onnx"})
MODEL_FILES = ASSETS | {"neural_pool", "run_neural_pool.sh"}
RUNTIME_FILES = frozenset({"xiaomi_neural_shadow/" + name for name in MODEL_FILES | {"runtime.sha256"}}
                          | {"xiaomi_native_wake_probe/native_wake_pool", "xiaomi_native_wake_probe/native_resident_session"})
ARCHIVE_FILES = RUNTIME_FILES | {"runtime-files.sha256"}
EXECUTABLE_MEMBERS = {"xiaomi_neural_shadow/ld-linux-armhf.so.3", "xiaomi_neural_shadow/neural_pool",
                      "xiaomi_native_wake_probe/native_wake_pool", "xiaomi_native_wake_probe/native_resident_session"}
HEADER_SHA256 = "90e4c96fc0c24c7cbedb24918bacc82c6bd896e35f992bf593e8c70fc54b01b4"
TARGET = {"device_model": "S12A", "root_partition": "boot1", "elf": "ELF32-LE-ARM",
          "build_target": "arm-linux-gnueabihf.2.25", "firmware_abi": "requires_separate_verification"}
VALIDATION = {"package_integrity": "verified", "arm_build": "completed",
              "arm_execution": "not_run", "device": "not_run", "human": "not_run"}
UPGRADE = {"supported": False, "allowed_source_packages": []}
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_RUNTIME_BYTES = 128 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")


class InvalidPackage(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def fail(code: str, message: str):
    raise InvalidPackage(code, message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    """Only read an explicitly selected regular file; no symlink or FIFO following."""
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            fail("UNSAFE_FILE", "需要普通文件，拒绝符号链接、目录和特殊文件。")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                fail("FILE_LIMIT", "文件类型或大小超出发布格式限制。")
            data = stream.read(limit + 1)
            if len(data) > limit:
                fail("FILE_LIMIT", "文件大小超出发布格式限制。")
            return data
    except OSError:
        fail("FILE_UNAVAILABLE", "所需文件缺失、不可读或在检查期间变化。")


def parse_manifest(data: bytes, expected: frozenset[str]) -> dict[str, str]:
    if len(data) > MAX_JSON_BYTES:
        fail("MANIFEST_LIMIT", "摘要清单超过大小限制。")
    try:
        text = data.decode("ascii")
    except UnicodeError:
        fail("MANIFEST_FORMAT", "摘要清单必须采用 ASCII 固定格式。")
    if not text.endswith("\n") or "\r" in text:
        fail("MANIFEST_FORMAT", "摘要清单必须使用 LF 换行并以换行结束。")
    result = {}
    for line in text.split("\n")[:-1]:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_./+-]+)", line)
        if not match or match[2] not in expected or match[2] in result:
            fail("MANIFEST_FORMAT", "摘要清单包含非法、重复或不允许的路径。")
        result[match[2]] = match[1]
    if result.keys() != expected:
        fail("MANIFEST_MEMBERS", "摘要清单未完整覆盖规定的文件集合。")
    return result


def manifest_bytes(hashes: dict[str, str]) -> bytes:
    return "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)).encode("ascii")


def check_hashes(hashes: dict[str, str], content: dict[str, bytes]):
    for name, value in hashes.items():
        if digest(content[name]) != value:
            fail("HASH_MISMATCH", "文件内容与摘要清单不一致。")


def check_elf(data: bytes):
    # This checks architecture only, not the dynamic ABI, firmware symbols or executability.
    if (len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01"
            or struct.unpack_from("<H", data, 16)[0] not in (2, 3)
            or struct.unpack_from("<H", data, 18)[0] != 40):
        fail("ELF_TARGET", "二进制不符合 ELF32、小端、ARM 的目标标识。")


def scan_tar_headers(raw: bytes) -> list[tuple[int, int]]:
    """Bound the raw layout before tarfile can process hidden/recursive extensions.

    The release format only needs regular members and short octal sizes. Do not
    ask tarfile to decode an extension or GNU binary number before enforcing
    these bounds; its iterator can consume such headers without yielding them.
    Header checksums and logical names are validated by tarfile afterwards.
    """
    if len(raw) > MAX_RUNTIME_BYTES:
        fail("ARCHIVE_LIMIT", "运行时归档解压后超过大小限制。")
    if len(raw) % 512:
        fail("ARCHIVE_TRAILING", "归档长度不是完整的 512 字节块。")
    offset = 0
    members = []
    while offset < len(raw):
        header = raw[offset:offset + 512]
        if header == bytes(512):
            if len(raw) - offset < 1024 or any(raw[offset:]):
                fail("ARCHIVE_TRAILING", "归档结尾无效或存在未检查的附加内容。")
            return members
        # Check type before size: even an empty global PAX header is forbidden.
        if header[156:157] not in (b"0", b"\x00"):
            fail("ARCHIVE_MEMBER", "归档含非普通文件或扩展成员头。")
        if len(members) >= len(ARCHIVE_FILES):
            fail("ARCHIVE_MEMBER", "归档成员数量超过固定文件集合。")
        size_field = header[124:136].rstrip(b"\x00 ")
        if not re.fullmatch(rb"[0-7]{1,11}", size_field):
            fail("ARCHIVE_SIZE", "归档成员大小不是受支持的有界八进制字段。")
        size = int(size_field, 8)
        if size > MAX_FILE_BYTES:
            fail("ARCHIVE_LIMIT", "归档成员超过大小限制。")
        body_end = offset + 512 + size
        next_offset = offset + 512 + ((size + 511) // 512) * 512
        if next_offset > len(raw):
            fail("ARCHIVE_TRUNCATED", "归档声明的成员跨度超出实际数据。")
        if any(raw[body_end:next_offset]):
            fail("ARCHIVE_PADDING", "归档成员填充区包含非零数据。")
        members.append((offset, size))
        offset = next_offset
    fail("ARCHIVE_TRAILING", "归档缺少两个完整的结束块。")


def check_runtime(compressed: bytes) -> dict:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            raw = stream.read(MAX_RUNTIME_BYTES + 1)
        if len(raw) > MAX_RUNTIME_BYTES:
            fail("ARCHIVE_LIMIT", "运行时归档解压后超过大小限制。")
        layout = scan_tar_headers(raw)
        content = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            for index, member in enumerate(archive):
                if (index >= len(layout) or (member.offset, member.size) != layout[index]
                        or member.offset_data != member.offset + 512):
                    fail("ARCHIVE_MEMBER", "归档解析结果与原始成员边界不一致。")
                if (member.name not in ARCHIVE_FILES or member.name in content
                        or not member.isfile() or member.linkname or member.pax_headers
                        or member.sparse is not None or member.mode & 0o7000):
                    fail("ARCHIVE_MEMBER", "归档含重复、非白名单路径、链接、特殊类型或扩展成员。")
                if member.name in EXECUTABLE_MEMBERS and not member.mode & 0o111:
                    fail("ARCHIVE_EXECUTABLE", "运行时程序缺少归档内的可执行权限。")
                if member.size < 0 or member.size > MAX_FILE_BYTES:
                    fail("ARCHIVE_LIMIT", "归档成员超过大小限制。")
                extracted = archive.extractfile(member)
                if extracted is None:
                    fail("ARCHIVE_MEMBER", "无法读取归档普通文件。")
                with extracted:
                    content[member.name] = extracted.read(MAX_FILE_BYTES + 1)
                if len(content[member.name]) != member.size:
                    fail("ARCHIVE_TRUNCATED", "归档成员被截断。")
            end = archive.offset
        if content.keys() != ARCHIVE_FILES or len(content) != len(layout):
            fail("ARCHIVE_MEMBERS", "归档未完整包含规定的运行时文件。")
        if len(raw) - end < 1024 or len(raw) % 512 or any(raw[end:]):
            fail("ARCHIVE_TRAILING", "归档结尾无效或存在未检查的附加内容。")
    except (OSError, EOFError, tarfile.TarError, zlib.error):
        fail("ARCHIVE_FORMAT", "运行时归档损坏或压缩格式无效。")
    hashes = parse_manifest(content["runtime-files.sha256"], RUNTIME_FILES)
    check_hashes(hashes, content)
    model = {name: content["xiaomi_neural_shadow/" + name] for name in MODEL_FILES}
    model_hashes = parse_manifest(content["xiaomi_neural_shadow/runtime.sha256"], MODEL_FILES)
    check_hashes(model_hashes, model)
    for name in ASSETS - {"silero_vad_v5.onnx"} | {"neural_pool"}:
        check_elf(model[name])
    for name in ("native_wake_pool", "native_resident_session"):
        check_elf(content["xiaomi_native_wake_probe/" + name])
    assets = {name: model_hashes[name] for name in sorted(ASSETS)}
    return {"runtime_unpacked_bytes": sum(len(value) for value in content.values()),
            "assets": assets, "assets_manifest_sha256": digest(manifest_bytes(assets))}


def read_json(path: Path) -> dict:
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail("JSON_DUPLICATE", "JSON 元数据包含重复键。")
            result[key] = value
        return result
    try:
        value = json.loads(read_regular(path, MAX_JSON_BYTES), object_pairs_hook=no_duplicates,
                           parse_constant=lambda _: fail("JSON_FORMAT", "JSON 元数据包含非标准数字。"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, InvalidPackage):
            raise
        fail("JSON_FORMAT", "JSON 元数据无效。")
    if not isinstance(value, dict):
        fail("JSON_FORMAT", "JSON 元数据必须是对象。")
    return value


def exact_keys(value, names, code="METADATA_SCHEMA"):
    if not isinstance(value, dict) or value.keys() != set(names):
        fail(code, "元数据字段缺失、未知或结构不符合本版格式。")


def make_metadata(manifest_hash: str, runtime: dict, source: dict) -> dict:
    return {"schema_version": 1, "package_type": "xiaomi-native-endpoint",
            "release_id": "sha256:" + manifest_hash, "package_manifest_sha256": manifest_hash,
            "source": source, "inputs": {"assets": runtime["assets"],
                "assets_manifest_sha256": runtime["assets_manifest_sha256"], "sherpa_header_sha256": HEADER_SHA256},
            "target": dict(TARGET), "validation": dict(VALIDATION),
            "upgrade": {"supported": False, "allowed_source_packages": []}}


def check_metadata(meta: dict, manifest_hash: str, runtime: dict):
    exact_keys(meta, ("schema_version", "package_type", "release_id", "package_manifest_sha256",
                      "source", "inputs", "target", "validation", "upgrade"))
    if type(meta["schema_version"]) is not int or meta["schema_version"] != 1 or meta["package_type"] != "xiaomi-native-endpoint":
        fail("METADATA_VERSION", "不支持此发布元数据版本或包类型。")
    if meta["package_manifest_sha256"] != manifest_hash or meta["release_id"] != "sha256:" + manifest_hash:
        fail("METADATA_BINDING", "发布元数据未绑定当前包清单。")
    source = meta["source"]
    exact_keys(source, ("revision", "dirty"))
    revision, dirty = source["revision"], source["dirty"]
    if revision is None:
        if dirty is not None:
            fail("METADATA_SOURCE", "未知源码版本不能声明工作区状态。")
    elif (not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision)
          or type(dirty) is not bool):
        fail("METADATA_SOURCE", "源码版本或工作区状态格式无效。")
    expected_inputs = {"assets": runtime["assets"], "assets_manifest_sha256": runtime["assets_manifest_sha256"],
                       "sherpa_header_sha256": HEADER_SHA256}
    if meta["inputs"] != expected_inputs:
        fail("METADATA_INPUTS", "构建输入摘要与包内资产或固定头文件约束不符。")
    upgrade = meta["upgrade"]
    if (meta["target"] != TARGET or meta["validation"] != VALIDATION or upgrade != UPGRADE
            or not isinstance(upgrade, dict) or upgrade.get("supported") is not False):
        fail("METADATA_CLAIMS", "目标约束、验证声明或升级规则不符合当前发布格式。")


def validate_package(directory: Path) -> dict:
    """Raise a bounded diagnostic for invalid content; no filesystem writes."""
    directory = Path(directory)
    try:
        if not stat.S_ISDIR(directory.lstat().st_mode):
            fail("PACKAGE_DIRECTORY", "包入口必须是实际目录，不能为符号链接。")
    except OSError:
        fail("PACKAGE_DIRECTORY", "包目录不存在或不可访问。")
    manifest = read_regular(directory / "package.sha256", MAX_JSON_BYTES)
    hashes = parse_manifest(manifest, PAYLOADS)
    content = {name: read_regular(directory / name) for name in sorted(PAYLOADS)}
    check_hashes(hashes, content)
    check_elf(content["native_asr.so"])
    check_elf(content["lifecycle"])
    runtime = check_runtime(content["runtime.tar.gz"])
    manifest_hash = digest(manifest)
    meta_path = directory / "release.json"
    metadata = None
    if os.path.lexists(meta_path):
        metadata = read_json(meta_path)
        check_metadata(metadata, manifest_hash, runtime)
    return {"package_manifest_sha256": manifest_hash, "payload_bytes": sum(map(len, content.values())),
            "runtime": runtime, "metadata": metadata}


def check_device_evidence(path: Path) -> dict:
    evidence = read_json(path)
    exact_keys(evidence, ("schema_version", "device_model", "root_partition", "installed_package_sha256"), "EVIDENCE_SCHEMA")
    if type(evidence["schema_version"]) is not int or evidence["schema_version"] != 1:
        fail("EVIDENCE_SCHEMA", "不支持此设备证据格式。")
    if (evidence["device_model"] not in ("S12A", "other") or evidence["root_partition"] not in ("boot0", "boot1", "unknown")
            or not isinstance(evidence["installed_package_sha256"], str) or not HEX.fullmatch(evidence["installed_package_sha256"])):
        fail("EVIDENCE_SCHEMA", "设备证据缺失或字段不符合固定格式。")
    return evidence


def inspect_release(directory: Path, device_evidence: Path | None = None) -> tuple[dict, int]:
    report = {"schema_version": 1, "package": {"status": "UNKNOWN"}, "release": {"status": "UNKNOWN"},
              "deployment": {"status": "UNKNOWN", "allowed": False}, "messages": []}
    try:
        checked = validate_package(directory)
    except InvalidPackage as exc:
        report["package"] = {"status": "FAIL", "code": exc.code}
        report["deployment"] = {"status": "BLOCKED", "allowed": False, "code": "INVALID_CANDIDATE"}
        report["messages"].append(str(exc))
        return report, 1
    report["package"] = {"status": "PASS", "manifest_sha256": checked["package_manifest_sha256"],
                         "payload_bytes": checked["payload_bytes"],
                         "runtime_unpacked_bytes": checked["runtime"]["runtime_unpacked_bytes"]}
    report["messages"].append("包体、运行时清单与 ARM 目标标识一致；未执行包内程序。")
    if checked["metadata"] is None:
        report["release"] = {"status": "UNKNOWN", "code": "LEGACY_METADATA_MISSING"}
        report["messages"].append("旧包缺少 release.json，源码来源与构建验证记录未知。")
    else:
        source = checked["metadata"]["source"]
        report["release"] = {"status": "PASS", "source": source, "provenance": "self_reported_unsigned"}
        report["messages"].append("元数据结构及包绑定一致；源码记录为构建机自述，没有签名认证。")
        if source["dirty"] is not False:
            report["messages"].append("源码工作区含未提交内容或版本未知，不能据此重建已发布源码。")
    if device_evidence is None:
        report["deployment"]["code"] = "DEVICE_EVIDENCE_MISSING"
        report["messages"].append("未提供设备证据；固件 ABI、空间、空闲状态及升级兼容性均未确认。")
        return report, 2
    try:
        evidence = check_device_evidence(device_evidence)
    except InvalidPackage as exc:
        report["deployment"] = {"status": "BLOCKED", "allowed": False, "code": exc.code}
        report["messages"].append(str(exc))
        return report, 1
    if evidence["device_model"] != "S12A" or evidence["root_partition"] == "boot0":
        code, message = "DEVICE_TARGET_MISMATCH", "设备型号或活动分区与候选包目标不符。"
    elif evidence["root_partition"] == "unknown":
        report["deployment"]["code"] = "DEVICE_PARTITION_UNKNOWN"
        report["messages"].append("设备活动分区未知，无法判断目标一致性。")
        return report, 2
    else:
        code, message = "UPGRADE_RULE_UNAVAILABLE", "尚无经验证的升级来源规则与整包回退流程；即使目标相符也不允许部署。"
    report["deployment"] = {"status": "BLOCKED", "allowed": False, "code": code}
    report["messages"].append(message)
    return report, 1
