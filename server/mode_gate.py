"""Reject disabled API calls before parsing bodies or touching model services."""
from starlette.responses import JSONResponse


FULL_PATHS = {
    "/api/v1/chat", "/api/v1/chat/stream", "/api/v1/asr", "/api/v1/route/asr",
    "/api/v1/voice_chat", "/api/v1/shell/chat", "/api/v1/stream/text_chat",
    "/api/v1/stream/chat", "/ws/voice",
}


class ServiceModeMiddleware:
    def __init__(self, app, mode_getter):
        self.app = app
        self.mode_getter = mode_getter

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path + "/"):
            path = path[len(root_path):]
        path = path.rstrip("/")
        disabled = path in FULL_PATHS or path.startswith("/api/v1/session/")
        if self.mode_getter() == "tts-only" and disabled:
            detail = "This endpoint is disabled in tts-only mode; use full mode"
            if scope["type"] == "http":
                await JSONResponse({"detail": detail}, status_code=503)(scope, receive, send)
                return
            if scope["type"] == "websocket":
                if "websocket.http.response" in scope.get("extensions", {}):
                    await send({"type": "websocket.http.response.start", "status": 503,
                                "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                    await send({"type": "websocket.http.response.body", "body": detail.encode()})
                else:
                    await send({"type": "websocket.close", "code": 1013, "reason": detail})
                return
        await self.app(scope, receive, send)
