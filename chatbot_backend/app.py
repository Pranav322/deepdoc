from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from codewiki.config import load_config
    from codewiki.chatbot.service import create_fastapi_app

    app = create_fastapi_app(REPO_ROOT, load_config(REPO_ROOT / ".codewiki.yaml"))
except Exception as _init_err:
    # Fallback app so the frontend gets a clear error instead of connection refused
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    _detail = str(_init_err)
    app = FastAPI(title="CodeWiki Chatbot (startup error)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def _health():
        return {"status": "error", "detail": _detail}

    @app.post("/query")
    def _query():
        return JSONResponse(status_code=503, content={"error": "startup_failed", "detail": _detail})
