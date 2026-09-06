"""Run only follow-up ASR; the speaker keeps its own LLM and TTS clients.

Example: python -m server.followup_asr --host 192.168.8.150 --model small
"""
import argparse
from contextlib import asynccontextmanager


def create_app(model: str, threads: int):
    import torch
    from fastapi import FastAPI
    from server import main

    @asynccontextmanager
    async def lifespan(app):
        torch.set_num_threads(threads)
        main.asr_client = main.WhisperASR(model_name=model, language="zh", device="cpu")
        # The processed-PCM path need not use the permissive gate retained for
        # old weak/raw multichannel recordings. Reject observed nonsense turns.
        main.asr_client.quality_min_logprob = -0.75
        yield
        main.asr_client = None

    app = FastAPI(title="Speaker follow-up ASR", lifespan=lifespan)
    app.add_api_route("/api/v1/route/asr", main.route_asr, methods=["POST"])

    @app.get("/")
    def health():
        return {"status": "ready", "service": "followup-asr", "model": model}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--model", default="small", help="Whisper model name or local .pt path")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("--threads must be positive")
    import uvicorn
    uvicorn.run(create_app(args.model, args.threads), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
