"""Shared configuration for the application and its command-line launcher."""
import os
from pathlib import Path

from dotenv import load_dotenv
import yaml


ROOT = Path(__file__).resolve().parents[1]
MODES = ("full", "tts-only")


def load_config(config_path=None):
    path = Path(config_path or os.environ.get("XIAOMI_SERVER_CONFIG") or ROOT / "config.yaml").resolve()
    # Shell exports take precedence. Values such as $(), backticks, and ${...}
    # remain literal dotenv data; they are never executed or interpolated.
    load_dotenv(path.with_name(".env"), override=False, interpolate=False)
    try:
        with path.open(encoding="utf-8") as source:
            config = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise ValueError("Invalid YAML in server configuration") from error
    if not isinstance(config, dict):
        raise ValueError("Server configuration must be a YAML mapping")

    def substitute(value):
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            return os.environ.get(value[2:-1], "")
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        if isinstance(value, list):
            return [substitute(item) for item in value]
        return value

    config = substitute(config)
    settings = config.setdefault("server", {})
    if not isinstance(settings, dict):
        raise ValueError("server must be a YAML mapping")
    mode = os.environ.get("XIAOMI_SERVER_MODE", settings.get("mode", "full"))
    if mode not in MODES:
        raise ValueError("server.mode must be full or tts-only")
    settings["mode"] = mode
    settings.setdefault("host", "0.0.0.0")
    settings.setdefault("port", 8080)
    settings.setdefault("reload", True)  # Preserve the original launcher default.
    settings.setdefault("cors_origins", ["*"])
    if not isinstance(settings["host"], str) or not settings["host"].strip():
        raise ValueError("server.host must be a nonempty string")
    raw_port = settings["port"]
    if isinstance(raw_port, bool) or not str(raw_port).isdecimal():
        raise ValueError("server.port must be an integer from 1 to 65535")
    settings["port"] = int(raw_port)
    if not 1 <= settings["port"] <= 65535:
        raise ValueError("server.port must be an integer from 1 to 65535")
    if not isinstance(settings["reload"], bool):
        raise ValueError("server.reload must be true or false")
    return config
