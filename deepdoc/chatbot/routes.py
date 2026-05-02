"""FastAPI route definitions for the chatbot service."""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .settings import chatbot_allowed_origins


class QueryRequest(BaseModel):
    """Incoming chatbot query payload."""

    question: str
    history: list[dict[str, str]] = Field(default_factory=list)


class DeepResearchRequest(QueryRequest):
    """Incoming deep-research payload."""

    max_rounds: int = Field(default=3, ge=1, le=6)


class CodeDeepRequest(QueryRequest):
    """Incoming code-deep payload."""

    max_rounds: int = Field(default=4, ge=1, le=8)


def create_fastapi_app(repo_root: Path, cfg: dict[str, Any]):
    from fastapi import Body, FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse

    from .service import ChatbotQueryService

    service = ChatbotQueryService(repo_root, cfg)
    app = FastAPI(title="DeepDoc Chatbot")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=chatbot_allowed_origins(cfg),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/query")
    def query(request: QueryRequest = Body(...)) -> dict[str, Any]:
        try:
            return service.query(request.question, request.history, mode="fast")
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_query_failed",
                    "detail": str(exc),
                },
            )

    @app.post("/deep-research")
    def deep_research(request: DeepResearchRequest = Body(...)) -> dict[str, Any]:
        try:
            return service.deep_research(
                request.question,
                request.history,
                max_rounds=request.max_rounds,
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_deep_research_failed",
                    "detail": str(exc),
                },
            )

    @app.post("/query/stream")
    def query_stream(request: QueryRequest = Body(...)):
        tokens: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

        def on_token(text: str) -> None:
            tokens.put(("token", {"text": text}))

        def run() -> None:
            try:
                result = service.query(
                    request.question,
                    request.history,
                    mode="fast",
                    token_callback=on_token,
                )
                tokens.put(("result", result))
            except Exception as exc:
                tokens.put(("error", {"error": "chatbot_query_failed", "detail": str(exc)}))
            finally:
                tokens.put(("done", {"status": "done"}))
                tokens.put(None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        def event_stream():
            while True:
                item = tokens.get()
                if item is None:
                    break
                event_name, payload = item
                yield f"event: {event_name}\n"
                yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/deep-research/stream")
    def deep_research_stream(request: DeepResearchRequest = Body(...)):
        tokens: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

        def on_token(text: str) -> None:
            tokens.put(("token", {"text": text}))

        def run() -> None:
            try:
                result = service.deep_research(
                    request.question,
                    request.history,
                    max_rounds=request.max_rounds,
                    token_callback=on_token,
                )
                tokens.put(("result", result))
            except Exception as exc:
                tokens.put(("error", {"error": "chatbot_deep_research_failed", "detail": str(exc)}))
            finally:
                tokens.put(("done", {"status": "done"}))
                tokens.put(None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        def event_stream():
            while True:
                item = tokens.get()
                if item is None:
                    break
                event_name, payload = item
                yield f"event: {event_name}\n"
                yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/code-deep")
    def code_deep(request: CodeDeepRequest = Body(...)) -> dict[str, Any]:
        try:
            return service.code_deep(
                request.question,
                request.history,
                max_rounds=request.max_rounds,
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_code_deep_failed",
                    "detail": str(exc),
                },
            )

    @app.post("/code-deep/stream")
    def code_deep_stream(request: CodeDeepRequest = Body(...)):
        events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

        def emit(event: dict[str, Any]) -> None:
            events.put(("trace", event))

        def run() -> None:
            try:
                result = service.code_deep(
                    request.question,
                    request.history,
                    max_rounds=request.max_rounds,
                    trace_callback=emit,
                )
                events.put(("result", result))
            except Exception as exc:
                events.put(
                    (
                        "error",
                        {
                            "error": "chatbot_code_deep_failed",
                            "detail": str(exc),
                        },
                    )
                )
            finally:
                events.put(("done", {"status": "done"}))
                events.put(None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        def event_stream():
            while True:
                item = events.get()
                if item is None:
                    break
                event_name, payload = item
                yield f"event: {event_name}\n"
                yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/query-context")
    def query_context(request: QueryRequest = Body(...)) -> dict[str, Any]:
        try:
            context = service.retrieve_context(
                request.question,
                request.history,
                mode="fast",
            )
            selected = service._select_prompt_hits(
                request.question,
                context.get("code_hits", []),
                context.get("artifact_hits", []),
                context.get("doc_hits", []),
                context.get("relationship_hits", []),
                service._retrieval_profile("fast"),
            )
            selected_hits = (
                selected.get("code_hits", [])
                + selected.get("artifact_hits", [])
                + selected.get("doc_hits", [])
                + selected.get("relationship_hits", [])
            )
            payload = {
                "question": request.question,
                "response_mode": "fast",
                "selected_chunks": len(selected_hits),
                "code_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("code_hits", [])
                ],
                "artifact_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("artifact_hits", [])
                ],
                "doc_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("doc_hits", [])
                    if hit.record.kind in {"doc_summary", "doc_full"}
                ],
                "repo_doc_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("doc_hits", [])
                    if hit.record.kind == "repo_doc"
                ],
                "relationship_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("relationship_hits", [])
                ],
            }
            payload["doc_links"] = service._doc_links(
                selected.get("doc_hits", []),
                selected.get("code_hits", []) + selected.get("artifact_hits", []),
            )
            payload.update(service._workspace_payload(request.question, payload, mode="fast"))
            payload = service._apply_evidence_contract(payload, mode="fast")
            payload.pop("answer", None)
            return payload
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_query_context_failed",
                    "detail": str(exc),
                },
            )

    return app
