"""
小米AI音箱 LLM 对话助手 - FastAPI 主服务
"""

import os
import asyncio
import json
import base64
from typing import Optional
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .llm.claude_client import ClaudeClient, OpenAIClient
from .llm.minimax_client import MiniMaxClient
from .asr.whisper_client import WhisperASR
from .tts.tts_client import ElevenLabsTTS, AzureTTS
from .tts.minimax_tts import MiniMaxTTS
from .tts.chattts_client import ChatTTSClient
from .tts.edge_tts_client import EdgeTTSClient
from fastapi.responses import Response
from starlette.responses import StreamingResponse
from .streaming_pipeline import StreamingPipeline
from .audio.processor import AudioProcessor


# 加载配置
def load_config():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config.yaml"
    )
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # 替换环境变量 (递归处理所有嵌套层)
    def _substitute(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    obj[k] = os.environ.get(v[2:-1], "")
                elif isinstance(v, (dict, list)):
                    _substitute(v)
        elif isinstance(obj, list):
            for item in obj:
                _substitute(item)
    _substitute(config)
    return config


config = load_config()


# 全局客户端
llm_client: Optional = None  # 默认 LLM client
llm_clients: dict[str, object] = {}
asr_client: Optional[WhisperASR] = None
tts_client: Optional[ElevenLabsTTS] = None
audio_processor = AudioProcessor()

# 对话历史 (简单内存存储，生产环境应使用 Redis 等)
conversation_histories: dict[str, list[dict]] = {}


def is_low_confidence_asr(info: dict) -> tuple[bool, str]:
    text = (info.get("text") or "").strip()
    compact = "".join(text.split())
    if not compact:
        return True, "empty_text"

    avg_logprob = float(info.get("avg_logprob", -10.0))
    no_speech_prob = float(info.get("no_speech_prob", 1.0))
    active_ratio = float(info.get("active_ratio", 0.0))
    speech_active_ratio = float(info.get("speech_active_ratio", active_ratio))
    rms = float(info.get("rms", 0.0))
    duration = float(info.get("duration", 0.0))
    speech_duration = float(info.get("speech_duration", duration))
    speech_rms = float(info.get("speech_rms", rms))

    if avg_logprob < -1.0:
        return True, f"low_logprob:{avg_logprob:.2f}"
    if no_speech_prob > 0.80:
        return True, f"no_speech:{no_speech_prob:.2f}"
    if no_speech_prob > 0.75 and avg_logprob < -0.25:
        return True, f"no_speech:{no_speech_prob:.2f}"
    if speech_duration < 0.35:
        return True, f"short_speech:{speech_duration:.2f}"

    # 小米音箱 8ch Capture 的追问录音经常整体能量很低，active_ratio 会接近 0。
    # 这种情况下优先相信 Whisper 的文本置信度，避免把“电脑怎么重启”这类
    # 可用短句误判为空；高 no_speech 和低 logprob 的幻觉仍会在上面被拦截。
    if len(compact) >= 4 and avg_logprob >= -0.75 and no_speech_prob < 0.70:
        return False, "ok"

    if duration >= 3.0 and speech_active_ratio < 0.008 and no_speech_prob > 0.55:
        return True, f"low_active_no_speech:{speech_active_ratio:.3f}/{no_speech_prob:.2f}"
    if duration >= 3.0 and speech_active_ratio < 0.006 and avg_logprob < -0.65:
        return True, f"low_active_ratio:{speech_active_ratio:.3f}"
    if speech_rms < 0.0008 and avg_logprob < -0.35:
        return True, f"low_speech_rms:{speech_rms:.5f}"

    return False, "ok"


def _compact_for_echo(text: str) -> str:
    import re

    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "").lower()


def is_likely_assistant_echo(text: str, session_id: str) -> tuple[bool, str]:
    """Reject ASR that is likely the speaker re-recording the last assistant answer."""
    current = _compact_for_echo(text)
    if len(current) < 6:
        return False, "too_short"

    history = conversation_histories.get(session_id, [])
    last_assistant = ""
    for item in reversed(history):
        if item.get("role") == "assistant":
            last_assistant = item.get("content") or ""
            break

    previous = _compact_for_echo(last_assistant)
    if len(previous) < 6:
        return False, "no_last_assistant"

    if current in previous:
        return True, "assistant_echo_substring"

    if len(current) >= 10 and previous in current:
        return True, "assistant_echo_contains_last"

    common = 0
    for i in range(0, max(0, len(current) - 1)):
        if current[i:i + 2] in previous:
            common += 1
    ratio = common / max(1, len(current) - 1)
    if len(current) >= 8 and ratio >= 0.82:
        return True, f"assistant_echo_bigram:{ratio:.2f}"

    return False, "not_echo"


def llm_display_name(client) -> str:
    if isinstance(client, MiniMaxClient):
        if client is llm_clients.get("deepseek"):
            return f"deepseek ({client.model})"
        return f"minimax ({client.model})"
    if isinstance(client, ClaudeClient):
        return f"claude ({client.model})"
    if isinstance(client, OpenAIClient):
        return f"openai ({client.model})"
    return "unknown"


def get_llm_client(backend: str = "default"):
    if backend and backend != "default":
        client = llm_clients.get(backend)
        if client:
            return client
        if backend not in ("minimax", "deepseek", "claude", "openai"):
            print(f"WARNING: Unknown backend '{backend}', using default LLM")
        else:
            print(f"WARNING: Backend '{backend}' not configured, using default LLM")
    return llm_client


async def synthesize_stream_error_audio(
    error_content: str,
    *,
    sample_rate: int,
    speed: float,
    volume: float,
) -> Optional[bytes]:
    """Return fallback PCM only for LLM errors.

    TTS errors mean one sentence failed to synthesize; playing "model timeout"
    is misleading and can create an extra fake assistant turn.
    """
    if error_content.startswith("TTS:"):
        print(f"[Stream] TTS error, skip sentence audio: {error_content[4:].strip()}", flush=True)
        return None

    print(f"[Stream] LLM error: {error_content}", flush=True)
    fallback_text = "模型连接超时了，请稍后再试。"
    try:
        fallback_wav = await tts_client.synthesize_pcm(
            fallback_text,
            sample_rate=sample_rate,
            speed=speed,
            volume=volume,
        )
        return fallback_wav[44:]
    except Exception as e:
        print(f"[Stream] fallback TTS error: {e}", flush=True)
        return b""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动和关闭时的初始化"""
    global llm_client, llm_clients, asr_client, tts_client

    print("Initializing services...")

    # 初始化 LLM 客户端
    llm_clients = {}
    if config["llm"]["minimax"]["api_key"]:
        llm_clients["minimax"] = MiniMaxClient(
            api_key=config["llm"]["minimax"]["api_key"],
            model=config["llm"]["minimax"]["model"],
            base_url=config["llm"]["minimax"].get("base_url", "https://api.minimax.chat/v1"),
            max_tokens=config["llm"]["minimax"]["max_tokens"],
            temperature=config["llm"]["minimax"]["temperature"],
            timeout=config["llm"]["minimax"].get("timeout", 45.0),
            max_retries=config["llm"]["minimax"].get("max_retries", 1),
        )
        print(f"MiniMax client initialized with model: {config['llm']['minimax']['model']}")
    if config["llm"].get("deepseek", {}).get("api_key"):
        llm_clients["deepseek"] = MiniMaxClient(
            api_key=config["llm"]["deepseek"]["api_key"],
            model=config["llm"]["deepseek"]["model"],
            base_url=config["llm"]["deepseek"].get("base_url", "https://api.deepseek.com"),
            max_tokens=config["llm"]["deepseek"]["max_tokens"],
            temperature=config["llm"]["deepseek"]["temperature"],
            timeout=config["llm"]["deepseek"].get("timeout", 45.0),
            max_retries=config["llm"]["deepseek"].get("max_retries", 1),
        )
        print(f"DeepSeek client initialized with model: {config['llm']['deepseek']['model']}")
    if config["llm"]["claude"]["api_key"]:
        llm_clients["claude"] = ClaudeClient(
            api_key=config["llm"]["claude"]["api_key"],
            model=config["llm"]["claude"]["model"],
            max_tokens=config["llm"]["claude"]["max_tokens"],
            temperature=config["llm"]["claude"]["temperature"],
        )
        print(f"Claude client initialized with model: {config['llm']['claude']['model']}")
    if config["llm"]["openai"]["api_key"]:
        llm_clients["openai"] = OpenAIClient(
            api_key=config["llm"]["openai"]["api_key"],
            model=config["llm"]["openai"]["model"],
            max_tokens=config["llm"]["openai"]["max_tokens"],
            temperature=config["llm"]["openai"]["temperature"],
        )
        print(f"OpenAI client initialized with model: {config['llm']['openai']['model']}")

    for name in ("minimax", "deepseek", "claude", "openai"):
        if name in llm_clients:
            llm_client = llm_clients[name]
            break
    else:
        print("WARNING: No LLM API key configured")

    # 初始化 ASR
    asr_provider = config["asr"]["provider"]
    if asr_provider == "whisper":
        asr_client = WhisperASR(
            model_name=config["asr"]["whisper"]["model"],
            language=config["asr"]["whisper"]["language"],
        )
        print(f"Whisper ASR initialized with model: {config['asr']['whisper']['model']}")

    # 初始化 TTS
    tts_provider = config["tts"]["provider"]
    if tts_provider == "edgetts":
        edge_voice = config["tts"].get("edgetts", {}).get("voice", "zh-CN-YunjianNeural")
        tts_client = EdgeTTSClient(voice=edge_voice)
        print(f"EdgeTTS client initialized (free, Microsoft), voice: {edge_voice}")
    elif tts_provider == "chattts":
        tts_client = ChatTTSClient(
            sample_rate=config["tts"]["chattts"].get("sample_rate", 24000),
        )
        print("ChatTTS client initialized (local)")
    elif tts_provider == "minimax" and config["tts"]["minimax"]["api_key"]:
        tts_client = MiniMaxTTS(
            api_key=config["tts"]["minimax"]["api_key"],
            voice_id=config["tts"]["minimax"]["voice_id"],
            model=config["tts"]["minimax"]["model"],
            base_url=config["tts"]["minimax"].get("base_url", "https://api.minimax.chat/v1"),
        )
        print(f"MiniMax TTS initialized with voice: {config['tts']['minimax']['voice_id']}")
    elif tts_provider == "elevenlabs" and config["tts"]["elevenlabs"]["api_key"]:
        tts_client = ElevenLabsTTS(
            api_key=config["tts"]["elevenlabs"]["api_key"],
            voice_id=config["tts"]["elevenlabs"]["voice_id"],
            model=config["tts"]["elevenlabs"]["model"],
        )
        print(f"ElevenLabs TTS initialized with voice: {config['tts']['elevenlabs']['voice_id']}")

    print("Services initialized successfully")

    yield

    print("Shutting down...")


app = FastAPI(
    title="小米AI音箱 LLM 对话助手",
    description="通过语音与 Claude/GPT 等大模型对话",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config["server"]["cors_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求模型
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    use_stream: bool = False
    backend: str = "default"


class ChatResponse(BaseModel):
    text: str
    audio: Optional[str] = None  # Base64 encoded audio


def shell_kv_response(values: dict[str, str]) -> Response:
    body = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    return Response(content=body.encode("utf-8"), media_type="text/plain; charset=utf-8")


def stream_llm_audio_response(
    user_text: str,
    session_id: str,
    backend: str,
    speed: float,
    volume: float,
    t_start=None,
):
    """Stream an LLM answer as WAV audio for the shell clients."""
    import struct
    import time as _time

    selected_llm = get_llm_client(backend)
    if not selected_llm or not tts_client:
        raise HTTPException(status_code=500, detail="Services not fully configured")

    if t_start is None:
        t_start = _time.time()

    history = conversation_histories.get(session_id, [])
    pipeline = StreamingPipeline(selected_llm, tts_client, sample_rate=32000, speed=speed, volume=volume)
    system_prompt = "你是一个语音助手，请用纯文本口语回答。禁止使用任何 Markdown 格式（如 **、*、#、- 等），不要用列表，直接说完整的句子。"
    full_text = []

    async def generate():
        max_samples = 180 * 32000
        max_data = max_samples * 2
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + max_data, b'WAVE', b'fmt ',
            16, 1, 1, 32000, 64000, 2, 16,
            b'data', max_data,
        )
        yield header

        t_llm_start = _time.time()
        async for chunk in pipeline.process(
            user_text,
            system_prompt=system_prompt,
            conversation_history=history,
        ):
            if chunk["type"] == "text":
                full_text.append(chunk["content"])
            elif chunk["type"] == "audio":
                yield chunk["data"]
            elif chunk["type"] == "error":
                fallback_pcm = await synthesize_stream_error_audio(
                    chunk["content"],
                    sample_rate=32000,
                    speed=speed,
                    volume=volume,
                )
                if fallback_pcm is None:
                    continue
                if fallback_pcm:
                    full_text.append("模型连接超时了，请稍后再试。")
                    yield fallback_pcm
                break

        final_response = "".join(full_text)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": final_response})
        conversation_histories[session_id] = history[-20:]

        t_now = _time.time()
        print(f"[{_time.strftime('%H:%M:%S')}] 🤖 LLM({t_now-t_llm_start:.1f}s): {final_response}", flush=True)
        print(f"[{_time.strftime('%H:%M:%S')}] ✅ 完成 总耗时 {t_now-t_start:.1f}s", flush=True)

    return StreamingResponse(
        generate(),
        media_type="audio/wav",
        headers={"X-Accel-Buffering": "no"},
    )


# API 端点

@app.get("/")
async def root():
    """健康检查"""
    return {
        "status": "ok",
        "service": "xiaomi_ai_llm",
        "llm": llm_display_name(llm_client) if llm_client else "unknown",
        "llm_backends": {
            name: llm_display_name(client)
            for name, client in llm_clients.items()
        },
        "asr_configured": asr_client is not None,
        "tts_configured": tts_client is not None,
    }


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """文字对话接口"""
    selected_llm = get_llm_client(request.backend)
    if not selected_llm:
        raise HTTPException(status_code=500, detail="LLM client not configured")

    # 获取对话历史
    history = conversation_histories.get(request.session_id, [])

    # 调用 LLM
    response_text = await selected_llm.chat(
        message=request.message,
        conversation_history=history,
    )

    # 更新对话历史
    history.append({"role": "user", "content": request.message})
    history.append({"role": "assistant", "content": response_text})
    conversation_histories[request.session_id] = history[-20:]  # 保留最近20条

    # 合成语音
    audio_b64 = None
    if tts_client and response_text:
        audio_data = await tts_client.synthesize(response_text)
        audio_b64 = base64.b64encode(audio_data).decode()

    return ChatResponse(text=response_text, audio=audio_b64)


@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口（返回 Server-Sent Events）"""
    selected_llm = get_llm_client(request.backend)
    if not selected_llm:
        raise HTTPException(status_code=500, detail="LLM client not configured")

    async def event_generator():
        history = conversation_histories.get(request.session_id, [])

        full_response = []
        async for text_chunk in selected_llm.chat_stream(
            message=request.message,
            conversation_history=history,
        ):
            full_response.append(text_chunk)
            yield f"data: {json.dumps({'type': 'text', 'content': text_chunk})}\n\n"

        # 更新历史
        final_response = "".join(full_response)
        history.append({"role": "user", "content": request.message})
        history.append({"role": "assistant", "content": final_response})
        conversation_histories[request.session_id] = history[-20:]

        yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"

    return event_generator()


@app.post("/api/v1/asr")
async def speech_to_text(file: UploadFile = File(...)):
    """语音识别接口"""
    if not asr_client:
        raise HTTPException(status_code=500, detail="ASR client not configured")

    audio_data = await file.read()

    try:
        text = await asr_client.transcribe(
            audio_data,
            sample_rate=config["audio"]["sample_rate"],
        )
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASR error: {str(e)}")


@app.post("/api/v1/route/asr")
async def route_asr(file: UploadFile = File(...), session_id: str = Form("shell")):
    """Shell endpoint: follow-up WAV -> ASR quality gate.

    The native-first client owns native/LLM routing for the first turn by
    reading Xiaomi's mibrain nlp_result_get result on the speaker. This endpoint
    is kept for compatibility with existing shell clients, but only decides
    whether follow-up ASR text is usable. Non-empty accepted text is returned as
    ROUTE=llm; rejected audio is returned as ROUTE=empty.
    """
    import time as _time

    if not asr_client:
        raise HTTPException(status_code=500, detail="ASR client not configured")

    audio_data = await file.read()
    if len(audio_data) < 100:
        raise HTTPException(status_code=400, detail="Audio data too short")

    t_asr = _time.time()
    try:
        if hasattr(asr_client, "transcribe_with_info"):
            asr_info = await asr_client.transcribe_with_info(
                audio_data,
                sample_rate=config["audio"]["sample_rate"],
            )
            user_text = asr_info["text"]
        else:
            user_text = await asr_client.transcribe(
                audio_data,
                sample_rate=config["audio"]["sample_rate"],
            )
            asr_info = {"text": user_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASR error: {str(e)}")

    low_conf, quality_reason = is_low_confidence_asr(asr_info)
    if low_conf:
        elapsed = _time.time() - t_asr
        print(
            f"[{_time.strftime('%H:%M:%S')}] 🎤 FOLLOWUP ASR({elapsed:.1f}s): "
            f"{user_text} -> empty ({quality_reason}; "
            f"logprob={float(asr_info.get('avg_logprob', -10.0)):.2f} "
            f"nospeech={float(asr_info.get('no_speech_prob', 1.0)):.2f} "
            f"speech={float(asr_info.get('speech_duration', 0.0)):.2f}s "
            f"trim={float(asr_info.get('trim_start', 0.0)):.2f}-{float(asr_info.get('trim_end', 0.0)):.2f}s "
            f"active={float(asr_info.get('active_ratio', 0.0)):.3f} "
            f"speech_active={float(asr_info.get('speech_active_ratio', 0.0)):.3f} "
            f"rms={float(asr_info.get('rms', 0.0)):.5f} "
            f"speech_rms={float(asr_info.get('speech_rms', 0.0)):.5f} "
            f"ch={int(asr_info.get('decode_channel', -1))} "
            f"ch_score={float(asr_info.get('decode_channel_score', 0.0)):.6f} "
            f"ch_peak={float(asr_info.get('decode_channel_peak', 0.0)):.5f} "
            f"ch_rms={float(asr_info.get('decode_channel_rms', 0.0)):.5f} "
            f"ch_active={float(asr_info.get('decode_channel_active_ratio', 0.0)):.3f})",
            flush=True,
        )
        return shell_kv_response({
            "ROUTE": "empty",
            "TEXT": "",
            "REASON": quality_reason,
        })

    is_echo, echo_reason = is_likely_assistant_echo(user_text, session_id)
    if is_echo:
        elapsed = _time.time() - t_asr
        print(
            f"[{_time.strftime('%H:%M:%S')}] 🎤 FOLLOWUP ASR({elapsed:.1f}s): "
            f"{user_text} -> empty ({echo_reason}; session={session_id})",
            flush=True,
        )
        return shell_kv_response({
            "ROUTE": "empty",
            "TEXT": "",
            "REASON": echo_reason,
        })

    elapsed = _time.time() - t_asr
    print(
        f"[{_time.strftime('%H:%M:%S')}] 🎤 FOLLOWUP ASR({elapsed:.1f}s): "
        f"{user_text} -> llm (asr_ok; "
        f"logprob={float(asr_info.get('avg_logprob', -10.0)):.2f} "
        f"nospeech={float(asr_info.get('no_speech_prob', 1.0)):.2f} "
        f"speech={float(asr_info.get('speech_duration', 0.0)):.2f}s "
        f"trim={float(asr_info.get('trim_start', 0.0)):.2f}-{float(asr_info.get('trim_end', 0.0)):.2f}s "
        f"active={float(asr_info.get('active_ratio', 0.0)):.3f} "
        f"speech_active={float(asr_info.get('speech_active_ratio', 0.0)):.3f} "
        f"rms={float(asr_info.get('rms', 0.0)):.5f} "
        f"speech_rms={float(asr_info.get('speech_rms', 0.0)):.5f} "
        f"ch={int(asr_info.get('decode_channel', -1))} "
        f"ch_score={float(asr_info.get('decode_channel_score', 0.0)):.6f} "
        f"ch_peak={float(asr_info.get('decode_channel_peak', 0.0)):.5f} "
        f"ch_rms={float(asr_info.get('decode_channel_rms', 0.0)):.5f} "
        f"ch_active={float(asr_info.get('decode_channel_active_ratio', 0.0)):.3f})",
        flush=True,
    )

    return shell_kv_response({
        "ROUTE": "llm",
        "TEXT": user_text.strip(),
        "REASON": "asr_ok",
    })


@app.post("/api/v1/tts")
async def text_to_speech(message: str):
    """语音合成接口"""
    if not tts_client:
        raise HTTPException(status_code=500, detail="TTS client not configured")

    try:
        audio_data = await tts_client.synthesize(message)
        audio_b64 = base64.b64encode(audio_data).decode()
        return {"audio": audio_b64, "format": "mp3"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")


@app.post("/api/v1/voice_chat")
async def voice_chat(file: UploadFile = File(...), session_id: str = "default"):
    """
    端到端语音对话接口
    接收语音 -> 识别 -> LLM -> 合成语音 -> 返回
    """
    if not llm_client or not asr_client or not tts_client:
        raise HTTPException(status_code=500, detail="Services not fully configured")

    # 1. 接收并识别语音
    audio_data = await file.read()
    try:
        user_text = await asr_client.transcribe(
            audio_data,
            sample_rate=config["audio"]["sample_rate"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASR error: {str(e)}")

    if not user_text:
        return ChatResponse(text="", audio=None)

    # 2. 调用 LLM
    history = conversation_histories.get(session_id, [])
    llm_response = await llm_client.chat(
        message=user_text,
        conversation_history=history,
    )

    # 3. 更新历史
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": llm_response})
    conversation_histories[session_id] = history[-20:]

    # 4. 合成语音
    audio_b64 = None
    try:
        tts_audio = await tts_client.synthesize(llm_response)
        audio_b64 = base64.b64encode(tts_audio).decode()
    except Exception as e:
        print(f"TTS error (continuing without audio): {e}")

    return ChatResponse(text=llm_response, audio=audio_b64)


@app.post("/api/v1/shell/chat")
async def shell_chat(file: UploadFile = File(...), session_id: str = "shell"):
    """
    Shell 客户端专用端点: 接收 WAV → ASR → LLM → TTS → 返回原始 WAV 二进制

    用法 (音箱端):
      curl -s -o /tmp/tts.wav -F "file=@/tmp/rec.wav" http://MAC_IP:8080/api/v1/shell/chat
      aplay -D hw:0,1 /tmp/tts.wav
    """
    if not llm_client or not asr_client or not tts_client:
        raise HTTPException(status_code=500, detail="Services not fully configured")

    audio_data = await file.read()
    if len(audio_data) < 100:
        raise HTTPException(status_code=400, detail="Audio data too short")

    try:
        user_text = await asr_client.transcribe(
            audio_data,
            sample_rate=config["audio"]["sample_rate"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASR error: {str(e)}")

    if not user_text:
        return Response(content=b"", media_type="audio/wav")

    print(f"[Voice] User: {user_text}")

    history = conversation_histories.get(session_id, [])
    llm_response = await llm_client.chat(
        message=user_text,
        conversation_history=history,
        system_prompt="你是一个智能语音助手，请用简洁、自然的口语回答。不要使用思考标签，直接回答即可。",
    )

    # 过滤掉 <think>...</think> 标签
    import re as _re
    llm_response = _re.sub(r'<think>.*?</think>\s*', '', llm_response, flags=_re.DOTALL).strip()

    print(f"[Voice] LLM: {llm_response}")

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": llm_response})
    conversation_histories[session_id] = history[-20:]

    try:
        if isinstance(tts_client, MiniMaxTTS):
            tts_audio = await tts_client.synthesize_pcm(llm_response, sample_rate=32000)
        else:
            tts_audio = await tts_client.synthesize(llm_response)
    except Exception as e:
        print(f"TTS error: {e}")
        tts_audio = b""

    return Response(content=tts_audio, media_type="audio/wav")


@app.post("/api/v1/stream/text_chat")
async def stream_text_chat(
    message: str = Form(...),
    session_id: str = Form("shell"),
    backend: str = Form("minimax"),
    speed: float = Form(1.0),
    volume: float = Form(1.0),
):
    """Stream LLM audio for text accepted by the speaker or follow-up ASR gate."""
    import time as _time

    if not message.strip():
        return Response(content=b"", media_type="audio/wav")

    print(
        f"[{_time.strftime('%H:%M:%S')}] 🌐 LLM 文本输入 → {backend} "
        f"(speed={speed}, volume={volume}): {message}",
        flush=True,
    )
    return stream_llm_audio_response(
        user_text=message,
        session_id=session_id,
        backend=backend,
        speed=speed,
        volume=volume,
    )


@app.post("/api/v1/stream/chat")
async def stream_chat(file: UploadFile = File(...), session_id: str = "shell", backend: str = "minimax", speed: float = 1.0, volume: float = 1.0):
    """
    流式语音对话端点
    接收 WAV → ASR → LLM 流式输出 → 逐句 TTS → 流式返回 PCM

    音箱端用法:
      mkfifo /tmp/stream_fifo
      curl -s -N -o /tmp/stream_fifo -F "file=@/tmp/rec.wav" \\
           http://MAC_IP:8080/api/v1/stream/chat &
      aplay -D hw:0,1 -f S16_LE -r 32000 -c 1 /tmp/stream_fifo 2>/dev/null &
    """
    import struct, time as _time

    selected_llm = get_llm_client(backend)
    if not selected_llm or not asr_client or not tts_client:
        raise HTTPException(status_code=500, detail="Services not fully configured")

    t_start = _time.time()
    audio_data = await file.read()
    size_mb = len(audio_data) / 1048576
    # 从 WAV 头读取实际时长
    duration = 0; channels = 0; sr_wav = 0; bits = 0
    if len(audio_data) > 44:
        channels = int.from_bytes(audio_data[22:24], 'little')
        sr_wav = int.from_bytes(audio_data[24:28], 'little')
        bits = int.from_bytes(audio_data[34:36], 'little')
        # 用总大小减估计头大小(72字节)算时长，避免 "data" 字符串误匹配
        byte_rate = sr_wav * channels * (bits // 8)
        data_size = max(0, len(audio_data) - 72)
        duration = data_size / byte_rate if byte_rate > 0 else 0
    print(f"[{_time.strftime('%H:%M:%S')}] 📥 收到录音: {size_mb:.1f}MB 语音{duration:.1f}s ({channels}ch {sr_wav}Hz {bits}bit)")

    if len(audio_data) < 100:
        raise HTTPException(status_code=400, detail="Audio data too short")

    # 1. ASR
    t_asr = _time.time()
    try:
        user_text = await asr_client.transcribe(
            audio_data,
            sample_rate=config["audio"]["sample_rate"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASR error: {str(e)}")
    t_asr_done = _time.time()

    if not user_text:
        print(f"[{_time.strftime('%H:%M:%S')}] ⚠️ ASR 无结果, 耗时 {t_asr_done-t_asr:.1f}s")
        return Response(content=b"", media_type="audio/wav")

    print(f"[{_time.strftime('%H:%M:%S')}] 🎤 ASR({t_asr_done-t_asr:.1f}s): {user_text}")

    # 2. LLM + TTS pipeline
    history = conversation_histories.get(session_id, [])
    pipeline = StreamingPipeline(selected_llm, tts_client, sample_rate=32000, speed=speed, volume=volume)
    system_prompt = "你是一个语音助手，请用纯文本口语回答。禁止使用任何 Markdown 格式（如 **、*、#、- 等），不要用列表，直接说完整的句子。"

    full_text = []

    async def generate():
        # 先发送 WAV 头 (44 字节，预留最大数据量给 aplay 解析)
        max_samples = 180 * 32000  # 最多 180 秒
        max_data = max_samples * 2  # 16-bit mono
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + max_data, b'WAVE', b'fmt ',
            16, 1, 1, 32000, 64000, 2, 16,
            b'data', max_data,
        )
        yield header

        async for chunk in pipeline.process(
            user_text,
            system_prompt=system_prompt,
            conversation_history=history,
        ):
            if chunk["type"] == "text":
                full_text.append(chunk["content"])
            elif chunk["type"] == "audio":
                yield chunk["data"]
            elif chunk["type"] == "error":
                fallback_pcm = await synthesize_stream_error_audio(
                    chunk["content"],
                    sample_rate=32000,
                    speed=speed,
                    volume=volume,
                )
                if fallback_pcm is None:
                    continue
                if fallback_pcm:
                    full_text.append("模型连接超时了，请稍后再试。")
                    yield fallback_pcm
                break

    _t_start_outer = t_start
    _t_asr_done_outer = t_asr_done

    async def wrapped_generate():
        async for data in generate():
            yield data
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": "".join(full_text)})
        conversation_histories[session_id] = history[-20:]
        full_response = "".join(full_text)
        t_now = _time.time()
        print(f"[{_time.strftime('%H:%M:%S')}] 🤖 LLM({t_now-_t_asr_done_outer:.1f}s): {full_response}", flush=True)
        print(f"[{_time.strftime('%H:%M:%S')}] ✅ 完成 总耗时 {t_now-_t_start_outer:.1f}s", flush=True)

    return StreamingResponse(
        wrapped_generate(),
        media_type="audio/wav",
        headers={"X-Accel-Buffering": "no"},
    )


@app.put("/api/v1/upload/{filename}")
async def upload_file(filename: str, request: Request):
    """临时端点：接收原始二进制体，存到 /tmp/"""
    data = await request.body()
    path = f"/tmp/{filename}"
    with open(path, "wb") as f:
        f.write(data)
    return {"status": "ok", "size": len(data), "path": path}


@app.post("/api/v1/upload_file")
async def upload_file_post(file: UploadFile = File(...)):
    """临时端点：接收 multipart 文件上传"""
    path = f"/tmp/{file.filename}"
    data = await file.read()
    with open(path, "wb") as f:
        f.write(data)
    return {"status": "ok", "size": len(data), "path": path}


@app.get("/api/v1/download/{filename}")
async def download_file(filename: str):
    """临时端点：下载文件"""
    from fastapi.responses import FileResponse
    return FileResponse(f"/tmp/{filename}")


@app.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    """
    WebSocket 语音对话
    客户端发送: {"type": "audio", "data": "<base64>"}
                 {"type": "text", "data": "直接发送文字"}
                 {"type": "end"}  结束对话
    服务端返回: {"type": "text", "content": "回复文字"}
                 {"type": "audio", "data": "<base64>"}
                 {"type": "done"}
    """
    await websocket.accept()
    session_id = str(id(websocket))  # 使用连接ID作为session

    try:
        while True:
            data = await websocket.receive_json()

            if data["type"] == "text":
                # 文字输入
                message = data["data"]
                history = conversation_histories.get(session_id, [])
                response = await llm_client.chat(message, conversation_history=history)

                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": response})
                conversation_histories[session_id] = history[-20:]

                await websocket.send_json({"type": "text", "content": response})

                # 合成语音
                if tts_client:
                    audio = await tts_client.synthesize(response)
                    audio_b64 = base64.b64encode(audio).decode()
                    await websocket.send_json({"type": "audio", "data": audio_b64})

                await websocket.send_json({"type": "done"})

            elif data["type"] == "audio":
                # 音频输入
                audio_b64 = data["data"]
                audio_data = base64.b64decode(audio_b64)

                try:
                    user_text = await asr_client.transcribe(
                        audio_data,
                        sample_rate=config["audio"]["sample_rate"],
                    )
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": str(e)})
                    continue

                if not user_text:
                    await websocket.send_json({"type": "text", "content": ""})
                    await websocket.send_json({"type": "done"})
                    continue

                await websocket.send_json({"type": "text", "content": user_text})

                # 调用 LLM
                history = conversation_histories.get(session_id, [])
                response = await llm_client.chat(user_text, conversation_history=history)

                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": response})
                conversation_histories[session_id] = history[-20:]

                await websocket.send_json({"type": "text", "content": response})

                # 合成语音
                if tts_client:
                    tts_audio = await tts_client.synthesize(response)
                    tts_b64 = base64.b64encode(tts_audio).decode()
                    await websocket.send_json({"type": "audio", "data": tts_b64})

                await websocket.send_json({"type": "done"})

            elif data["type"] == "end":
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except:
            pass


@app.delete("/api/v1/session/{session_id}")
async def clear_session(session_id: str):
    """清除对话历史"""
    if session_id in conversation_histories:
        del conversation_histories[session_id]
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config["server"]["host"],
        port=config["server"]["port"],
        reload=False,
    )
