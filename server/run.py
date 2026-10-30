"""Launch the optional server using the same configuration as the application."""
import argparse
import os
from pathlib import Path

from .configuration import MODES, ROOT, load_config


def main(argv=None):
    parser = argparse.ArgumentParser(description="启动小米音箱可选服务端")
    parser.add_argument("--config", help="配置文件；读取该文件同目录下的 .env")
    parser.add_argument("--mode", choices=MODES, help="覆盖 server.mode")
    reload_group = parser.add_mutually_exclusive_group()
    reload_group.add_argument("--reload", dest="reload", action="store_true")
    reload_group.add_argument("--no-reload", dest="reload", action="store_false")
    parser.set_defaults(reload=None)
    args = parser.parse_args(argv)
    # Freeze the selected file before reading .env. Reload workers and the app
    # must not be redirected by a path variable inside that file's .env.
    config_path = args.config or os.environ.get("XIAOMI_SERVER_CONFIG") or ROOT / "config.yaml"
    os.environ["XIAOMI_SERVER_CONFIG"] = str(Path(config_path).resolve())
    if args.mode:
        os.environ["XIAOMI_SERVER_MODE"] = args.mode
    try:
        config = load_config()
    except (OSError, ValueError) as error:
        parser.error(str(error))
    settings = config["server"]
    reload_enabled = settings["reload"] if args.reload is None else args.reload
    print(f"Starting mode={settings['mode']} at {settings['host']}:{settings['port']} (reload={reload_enabled})", flush=True)
    import uvicorn
    uvicorn.run("server.main:app", host=settings["host"], port=settings["port"], reload=reload_enabled)


if __name__ == "__main__":
    main()
