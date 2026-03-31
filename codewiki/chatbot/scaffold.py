"""Generated backend scaffold for chatbot-enabled repos."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from .settings import chatbot_backend_base_url, chatbot_enabled


def scaffold_chatbot_backend(repo_root: Path, cfg: dict) -> None:
    backend_dir = repo_root / "chatbot_backend"
    if not chatbot_enabled(cfg):
        if backend_dir.exists():
            return
        return

    files = {
        backend_dir / "app.py": _app_py(),
        backend_dir / "schemas.py": _schemas_py(),
        backend_dir / "settings.py": _settings_py(cfg),
        backend_dir / "requirements.txt": _requirements_txt(),
        backend_dir / ".env.example": _env_example(),
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _app_py() -> str:
    return dedent(
        """\
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
        """
    )


def _schemas_py() -> str:
    return dedent(
        """\
        from typing import Any

        from pydantic import BaseModel, Field


        class QueryRequest(BaseModel):
            question: str
            history: list[dict[str, str]] = Field(default_factory=list)


        class QueryResponse(BaseModel):
            answer: str
            code_citations: list[dict[str, Any]]
            artifact_citations: list[dict[str, Any]]
            doc_links: list[dict[str, Any]]
            used_chunks: int
        """
    )


def _settings_py(cfg: dict) -> str:
    return dedent(
        f"""\
        CHATBOT_BASE_URL = {chatbot_backend_base_url(cfg)!r}
        """
    )


def _requirements_txt() -> str:
    return "\n".join(
        [
            "codewiki",
            "fastapi>=0.115",
            "uvicorn>=0.30",
            "httpx>=0.27",
            "numpy>=1.26",
            "faiss-cpu>=1.8.0",
            "litellm>=1.40",
            "",
        ]
    )


def _env_example() -> str:
    return "\n".join(
        [
            "CODEWIKI_CHAT_API_KEY=",
            "CODEWIKI_EMBED_API_KEY=",
            "",
        ]
    )
