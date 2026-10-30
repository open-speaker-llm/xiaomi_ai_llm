"""Provider factories; optional model dependencies are imported only when needed."""


def create_llm_clients(settings, *, clients=None):
    # The lifespan supplies its registry so earlier clients remain reachable
    # for cleanup if a later provider constructor raises.
    if clients is None:
        clients = {}
    compatible_defaults = {
        "minimax": ("MiniMax-M2.7", "https://api.minimaxi.com/v1", 1024, 0.7),
        "deepseek": ("deepseek-flash", "https://api.deepseek.com", 1024, 0.7),
        "glm": ("glm-5.3-flash", "https://open.bigmodel.cn/api/paas/v4", 4096, 0.7),
        "kimi": ("kimi-k2.6", "https://api.moonshot.cn/v1", 1024, 0.6),
    }
    for name, (model, base_url, max_tokens, temperature) in compatible_defaults.items():
        provider = settings.get(name, {})
        if not provider.get("api_key"):
            continue
        from .llm.minimax_client import MiniMaxClient
        clients[name] = MiniMaxClient(
            api_key=provider["api_key"], model=provider.get("model", model),
            base_url=provider.get("base_url", base_url),
            max_tokens=provider.get("max_tokens", max_tokens),
            temperature=provider.get("temperature", temperature),
            timeout=provider.get("timeout", 45.0), max_retries=provider.get("max_retries", 1),
            reasoning_effort=provider.get("reasoning_effort", "low"),
        )
    for name, model in (("claude", "claude-sonnet-4-20250514"), ("openai", "gpt-4o-mini")):
        provider = settings.get(name, {})
        if not provider.get("api_key"):
            continue
        from .llm.claude_client import ClaudeClient, OpenAIClient
        client_type = ClaudeClient if name == "claude" else OpenAIClient
        clients[name] = client_type(
            api_key=provider["api_key"], model=provider.get("model", model),
            max_tokens=provider.get("max_tokens", 1024), temperature=provider.get("temperature", 0.7),
        )
    return clients


def create_asr_client(settings):
    if settings.get("provider") == "whisper":
        from .asr.whisper_client import WhisperASR
        provider = settings.get("whisper", {})
        return WhisperASR(model_name=provider.get("model", "medium"), language=provider.get("language", "zh"))
    return None


def create_tts_client(settings):
    name = settings.get("provider", "edgetts")
    provider = settings.get(name, {})
    if name == "edgetts":
        from .tts.edge_tts_client import EdgeTTSClient
        return EdgeTTSClient(voice=provider.get("voice", "zh-CN-YunjianNeural"))
    if name == "chattts":
        from .tts.chattts_client import ChatTTSClient
        return ChatTTSClient(sample_rate=provider.get("sample_rate", 24000))
    if name == "minimax" and provider.get("api_key"):
        from .tts.minimax_tts import MiniMaxTTS
        return MiniMaxTTS(
            api_key=provider["api_key"], voice_id=provider["voice_id"], model=provider["model"],
            base_url=provider.get("base_url", "https://api.minimax.chat/v1"),
        )
    if name == "elevenlabs" and provider.get("api_key"):
        from .tts.tts_client import ElevenLabsTTS
        return ElevenLabsTTS(api_key=provider["api_key"], voice_id=provider["voice_id"], model=provider["model"])
    return None
