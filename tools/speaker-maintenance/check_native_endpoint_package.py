#!/usr/bin/env python3
"""本机只读检查候选整包；不联网、不执行包内代码、不批准或执行部署。"""
import argparse
import json
from pathlib import Path
import sys

from native_endpoint_release import inspect_release


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(64, "参数错误：请使用 --help 查看本机预检用法。\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True, help="本机候选包或旧包目录")
    parser.add_argument("--device-evidence", type=Path, help="可选的脱敏离线设备证据 JSON；不会连接设备")
    args = parser.parse_args(argv)
    report, code = inspect_release(args.package, args.device_evidence)
    report["exit_code"] = code
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"包体：{report['package']['status']}；发布记录：{report['release']['status']}；部署：{report['deployment']['status']}（不允许部署）", file=sys.stderr)
    for message in report["messages"]:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
