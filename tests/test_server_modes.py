"""Service mode, launcher configuration, and optional dependency isolation."""
import asyncio
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
import yaml

from server import main, runtime
from server.configuration import load_config
from server.mode_gate import FULL_PATHS, ServiceModeMiddleware
from server.run import main as launch


ROOT = Path(__file__).resolve().parents[1]


class ServerConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="xiaomi-config-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.yaml"
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def write_config(self, settings):
        self.path.write_text(yaml.safe_dump(settings))

    def test_dotenv_preserves_literal_text_and_exported_values_win(self):
        marker = Path(self.directory.name) / "must-not-exist"
        literal = f"quoted # text $(touch {marker}) `touch {marker}` ${{EXPORTED}}"
        self.path.with_name(".env").write_text(
            f"SECRET='{literal}'\nEXPORTED=dotenv\nTEST_PORT=9123\n"
        )
        os.environ["EXPORTED"] = "shell-value"
        self.write_config({"server": {"port": "${TEST_PORT}"},
                           "test": {"secret": "${SECRET}", "exported": "${EXPORTED}"}})
        config = load_config(self.path)
        self.assertEqual(config["test"]["secret"], literal)
        self.assertEqual(config["test"]["exported"], "shell-value")
        self.assertEqual(config["server"]["port"], 9123)
        self.assertFalse(marker.exists())

    def test_full_and_reload_defaults_preserve_existing_launch_behavior(self):
        self.write_config({})
        settings = load_config(self.path)["server"]
        self.assertEqual(settings["mode"], "full")
        self.assertEqual((settings["host"], settings["port"], settings["reload"]),
                         ("0.0.0.0", 8080, True))

    def test_invalid_modes_and_ports_fail_before_startup(self):
        for settings in ({"mode": "native"}, {"port": 0}, {"port": 65536},
                         {"port": 1.5}, {"port": True}, {"port": "abc"}, {"reload": "false"}):
            with self.subTest(settings=settings):
                self.write_config({"server": settings})
                with self.assertRaises(ValueError):
                    load_config(self.path)

    def test_launcher_and_application_read_the_same_custom_port_and_mode(self):
        self.write_config({"server": {"mode": "full", "host": "127.0.0.1", "port": 9234}})
        with patch("uvicorn.run") as run, redirect_stdout(io.StringIO()):
            launch(["--config", str(self.path), "--mode", "tts-only", "--no-reload"])
        run.assert_called_once_with("server.main:app", host="127.0.0.1", port=9234, reload=False)
        app_settings = load_config()["server"]
        self.assertEqual(app_settings["mode"], "tts-only")
        self.assertEqual(app_settings["port"], 9234)

    def test_dotenv_mode_and_config_reload_are_used_without_cli_override(self):
        self.write_config({"server": {"reload": False}})
        self.path.with_name(".env").write_text("XIAOMI_SERVER_MODE=tts-only\n")
        with patch("uvicorn.run") as run, redirect_stdout(io.StringIO()):
            launch(["--config", str(self.path)])
        self.assertEqual(load_config()["server"]["mode"], "tts-only")
        self.assertFalse(run.call_args.kwargs["reload"])

    def test_dotenv_cannot_redirect_app_or_reload_worker_to_another_config(self):
        self.write_config({"server": {"port": 19001, "reload": False}})
        other = Path(self.directory.name) / "other.yaml"
        other.write_text("server:\n  port: 19002\n")
        self.path.with_name(".env").write_text(f"XIAOMI_SERVER_CONFIG={other}\n")
        with patch("server.run.ROOT", self.path.parent), patch("uvicorn.run") as run, \
                redirect_stdout(io.StringIO()):
            launch([])
        self.assertEqual(run.call_args.kwargs["port"], 19001)
        self.assertEqual(os.environ["XIAOMI_SERVER_CONFIG"], str(self.path.resolve()))
        self.assertEqual(load_config()["server"]["port"], 19001)


class ServerModeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = {
            "server": {"mode": "tts-only"},
            "tts": {"provider": "edgetts"},
            "asr": {"provider": "whisper"},
            "llm": {"default_backend": "deepseek"},
        }
        self.patches = [patch.object(main, "config", self.settings),
                        patch.object(main, "llm_clients", {}), patch.object(main, "llm_client", None),
                        patch.object(main, "asr_client", None), patch.object(main, "tts_client", None)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def test_tts_only_skips_model_factories_and_reports_disabled_components(self):
        with patch.object(main, "create_tts_client", return_value=object()), \
                patch.object(main, "create_llm_clients") as llm, \
                patch.object(main, "create_asr_client") as asr:
            async with main.lifespan(main.app):
                response = await self.client.get("/")
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["mode"], "tts-only")
                self.assertEqual(result["components"]["llm"]["state"], "disabled")
                self.assertEqual(result["components"]["asr"]["state"], "disabled")
                self.assertEqual(result["components"]["tts"]["state"], "ready")
                self.assertFalse(result["asr_configured"])
                self.assertTrue(result["tts_configured"])
            llm.assert_not_called()
            asr.assert_not_called()

    async def test_disabled_http_routes_return_503_before_body_validation(self):
        for path in sorted(FULL_PATHS - {"/ws/voice"}):
            with self.subTest(path=path):
                response = await self.client.post(path)
                self.assertEqual(response.status_code, 503)
                self.assertIn("tts-only", response.json()["detail"])
        response = await self.client.delete("/api/v1/session/test")
        self.assertEqual(response.status_code, 503)

    async def test_full_initializes_all_components_and_keeps_backend_selection(self):
        self.settings["server"]["mode"] = "full"
        model = SimpleNamespace(model="model-test", client=SimpleNamespace(close=AsyncMock()))
        with patch.object(main, "create_tts_client", return_value=object()) as tts, \
                patch.object(main, "create_llm_clients", return_value={"deepseek": model}) as llm, \
                patch.object(main, "create_asr_client", return_value=object()) as asr:
            async with main.lifespan(main.app):
                result = (await self.client.get("/")).json()
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["llm"], "deepseek (model-test)")
                self.assertEqual(result["components"]["asr"]["state"], "ready")
                self.assertIs(main.get_llm_client("deepseek"), model)
            llm.assert_called_once_with(self.settings["llm"], clients={})
            asr.assert_called_once_with(self.settings["asr"])
            tts.assert_called_once_with(self.settings["tts"])
            model.client.close.assert_awaited_once()

    async def test_full_without_llm_keeps_tts_available_and_reports_degraded(self):
        self.settings["server"]["mode"] = "full"
        with patch.object(main, "create_tts_client", return_value=object()), \
                patch.object(main, "create_llm_clients", return_value={}), \
                patch.object(main, "create_asr_client", return_value=None):
            async with main.lifespan(main.app):
                result = (await self.client.get("/")).json()
                self.assertEqual(result["status"], "degraded")
                self.assertEqual(result["components"]["llm"]["state"], "not_configured")
                self.assertTrue(result["tts_configured"])
                response = await self.client.post("/api/v1/chat", json={"message": "test"})
                self.assertEqual(response.status_code, 500)  # Existing full-mode error contract.

    async def test_asr_startup_failure_closes_previously_initialized_llm(self):
        self.settings["server"]["mode"] = "full"
        model = SimpleNamespace(model="model-test", client=SimpleNamespace(close=AsyncMock()))
        with patch.object(main, "create_tts_client", return_value=object()), \
                patch.object(main, "create_llm_clients", return_value={"deepseek": model}), \
                patch.object(main, "create_asr_client", side_effect=RuntimeError("ASR startup failed")):
            with self.assertRaisesRegex(RuntimeError, "ASR startup failed"):
                async with main.lifespan(main.app):
                    self.fail("Startup should not reach ready state")
        model.client.close.assert_awaited_once()

    async def test_one_sdk_close_failure_does_not_skip_other_clients(self):
        self.settings["server"]["mode"] = "full"
        first = SimpleNamespace(client=SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("close failed"))))
        second = SimpleNamespace(client=SimpleNamespace(close=AsyncMock()))
        with patch.object(main, "create_tts_client", return_value=object()), \
                patch.object(main, "create_llm_clients", return_value={"deepseek": first, "kimi": second}), \
                patch.object(main, "create_asr_client", return_value=object()), \
                redirect_stdout(io.StringIO()) as output:
            async with main.lifespan(main.app):
                pass
        first.client.close.assert_awaited_once()
        second.client.close.assert_awaited_once()
        self.assertIn("Failed to close LLM client deepseek", output.getvalue())

    async def test_later_provider_constructor_failure_closes_earlier_sdk(self):
        self.settings["server"]["mode"] = "full"
        self.settings["llm"].update({"minimax": {"api_key": "test"}, "deepseek": {"api_key": "test"}})
        first = SimpleNamespace(client=SimpleNamespace(close=AsyncMock()))
        constructor = Mock(side_effect=[first, RuntimeError("second provider failed")])
        fake_module = SimpleNamespace(MiniMaxClient=constructor)
        with patch.dict(sys.modules, {"server.llm.minimax_client": fake_module}), \
                patch.object(main, "create_tts_client", return_value=object()), \
                patch.object(main, "create_asr_client") as asr:
            with self.assertRaisesRegex(RuntimeError, "second provider failed"):
                async with main.lifespan(main.app):
                    self.fail("Startup should not reach ready state")
        self.assertEqual(constructor.call_count, 2)
        first.client.close.assert_awaited_once()
        asr.assert_not_called()

    async def test_websocket_mode_denial_uses_503_or_explicit_close(self):
        for extensions in ({"websocket.http.response": {}}, {}):
            with self.subTest(extensions=extensions):
                called = AsyncMock()
                send = AsyncMock()
                middleware = ServiceModeMiddleware(called, lambda: "tts-only")
                await middleware({"type": "websocket", "path": "/ws/voice", "extensions": extensions},
                                 AsyncMock(), send)
                called.assert_not_awaited()
                first = send.call_args_list[0].args[0]
                self.assertEqual(first.get("status") if extensions else first.get("code"),
                                 503 if extensions else 1013)


class ProviderIsolationTest(unittest.TestCase):
    def test_edge_tts_missing_ffmpeg_has_actionable_startup_error(self):
        with patch("server.tts.edge_tts_client.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg.*PATH"):
                runtime.create_tts_client({"provider": "edgetts"})

    def test_unconfigured_providers_do_not_import_sdks(self):
        self.assertEqual(runtime.create_llm_clients({}), {})
        self.assertIsNone(runtime.create_asr_client({"provider": "disabled"}))

    def test_tts_only_can_start_with_model_and_audio_imports_blocked(self):
        with tempfile.TemporaryDirectory(prefix="xiaomi-import-test-") as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("server:\n  mode: tts-only\ntts:\n  provider: edgetts\n")
            code = r'''
import asyncio, importlib.abc, json, sys
from unittest.mock import patch
blocked = ('whisper', 'torch', 'openai', 'anthropic', 'numpy', 'soundfile',
           'server.asr', 'server.llm', 'server.audio')
class RejectOptionalModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            raise AssertionError('disabled dependency imported: ' + fullname)
sys.meta_path.insert(0, RejectOptionalModels())
from server import main
async def run():
    with patch('server.tts.edge_tts_client.shutil.which', return_value='/test/ffmpeg'):
        async with main.lifespan(main.app):
            result = await main.root()
            assert result['status'] == 'ok', result
            assert result['components']['llm']['state'] == 'disabled'
            assert result['components']['asr']['state'] == 'disabled'
            assert not any(any(n == prefix or n.startswith(prefix + '.') for prefix in blocked) for n in sys.modules)
            print(json.dumps({'isolated': True, 'mode': result['mode']}))
asyncio.run(run())
'''
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                                    env={"PATH": os.environ.get("PATH", ""),
                                         "XIAOMI_SERVER_CONFIG": str(config_path)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"isolated": true', result.stdout)


if __name__ == "__main__":
    unittest.main()
