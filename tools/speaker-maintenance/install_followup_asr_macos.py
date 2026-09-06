#!/usr/bin/env python3
"""Install the ASR-only service and verified Whisper small model for macOS login.

Copies source into Application Support so it does not depend on a temporary
worktree. Requires an existing Python environment with project dependencies.
Does not load the LaunchAgent; inspect the printed launchctl command first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import sys

SMALL_SHA256 = '9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794'
LABEL = 'org.open-speaker-llm.followup-asr'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True, type=Path)
    parser.add_argument('--model-file', required=True, type=Path)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--runtime-dir', type=Path,
                        default=Path.home() / 'Library/Application Support/xiaomi-ai-llm/followup-asr')
    parser.add_argument('--launch-agents-dir', type=Path, default=Path.home() / 'Library/LaunchAgents')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('macOS only')
    if not args.python.is_file() or not os.access(args.python, os.X_OK):
        parser.error('--python must be an executable Python environment')
    if digest(args.model_file) != SMALL_SHA256:
        parser.error('model does not match the verified official Whisper small checksum')
    root = Path(__file__).resolve().parents[2]
    runtime = args.runtime_dir.expanduser().absolute()
    agent = args.launch_agents_dir / (LABEL + '.plist')
    if (runtime / 'app').exists() or agent.exists():
        parser.error('installation exists; back it up and stop the service before replacing it')
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime, 0o700)
    app = runtime / 'app'
    app.mkdir(mode=0o700)
    shutil.copytree(root / 'server', app / 'server', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # main.py also constructs its unused main-app CORS middleware on import.
    # No LLM/TTS credentials or initialization are needed by this ASR service.
    (app / 'config.yaml').write_text('audio:\n  sample_rate: 16000\nserver:\n  cors_origins: []\n')
    model = runtime / 'small.pt'
    shutil.copyfile(args.model_file, model)
    os.chmod(model, 0o600)
    manifest = {str(p.relative_to(app)): digest(p) for p in sorted(app.rglob('*')) if p.is_file()}
    (runtime / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    args.launch_agents_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'Label': LABEL,
        'ProgramArguments': [str(args.python.absolute()), '-m', 'server.followup_asr',
                             '--host', args.host, '--port', str(args.port), '--model', str(model), '--threads', '4'],
        'WorkingDirectory': str(app),
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 15,
        'EnvironmentVariables': {'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
        'StandardOutPath': str(runtime / 'service.log'),
        'StandardErrorPath': str(runtime / 'service.err.log'),
    }
    with agent.open('xb') as stream:
        plistlib.dump(payload, stream)
    os.chmod(agent, 0o600)
    print(json.dumps({'runtime': str(runtime), 'launch_agent': str(agent),
                      'label': LABEL, 'model_sha256': SMALL_SHA256}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
