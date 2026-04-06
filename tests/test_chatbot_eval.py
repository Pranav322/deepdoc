from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from deepdoc.chatbot.chunker import build_code_chunks, build_relationship_chunks
from deepdoc.chatbot.persistence import save_corpus
from deepdoc.chatbot.service import ChatbotQueryService
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.persistence_v2 import save_plan
from deepdoc.planner import RepoScan
from tests.conftest import make_bucket, make_plan


class _KeywordEmbedClient:
    _vocab = (
        "django",
        "express",
        "fastify",
        "falcon",
        "go",
        "laravel",
        "vue",
        "route",
        "routes",
        "router",
        "middleware",
        "viewset",
        "request",
        "response",
        "props",
        "pinia",
        "emit",
        "users",
        "login",
        "auth",
        "audit",
    )

    def embed(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            vectors.append([float(lower.count(token)) for token in self._vocab])
        return vectors


class _CapturingChatClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, system: str, user: str) -> str:
        if "alternative search queries" in system:
            return ""
        if "relevance scorer" in system.lower() or "Rate each chunk" in user:
            lines = [
                line
                for line in user.splitlines()
                if line.strip() and line.strip()[0].isdigit()
            ]
            return "\n".join("8" for _ in lines) if lines else "8"
        self.prompts.append(user)
        return "Grounded answer"


def _repo_scan_for_framework(framework: str) -> tuple[RepoScan, list[str], str]:
    if framework == "django":
        rel_path = "users/views.py"
        parsed = ParsedFile(
            path=Path(rel_path),
            language="python",
            symbols=[
                Symbol(
                    name="UserViewSet",
                    kind="class",
                    signature="class UserViewSet(ModelViewSet)",
                    start_line=1,
                    end_line=20,
                ),
                Symbol(
                    name="list",
                    kind="method",
                    signature="def list(self, request)",
                    start_line=2,
                    end_line=6,
                ),
            ],
            imports=["from rest_framework.viewsets import ModelViewSet"],
        )
        content = "class UserViewSet(ModelViewSet):\n    def list(self, request):\n        return []\n"
        endpoint = {
            "method": "GET",
            "path": "/api/users",
            "handler": "UserViewSet.list",
            "file": rel_path,
            "route_file": "users/urls.py",
            "handler_file": rel_path,
            "middleware": [],
            "request_body": "",
            "response_type": "",
            "framework": "django",
        }
        question = "Which django routes and viewsets handle users?"
        expected = ["django routes: GET /api/users -> UserViewSet.list", "/api/users"]
    elif framework == "express":
        rel_path = "src/routes/users.js"
        parsed = ParsedFile(
            path=Path(rel_path),
            language="javascript",
            symbols=[
                Symbol(
                    name="listUsers",
                    kind="function",
                    signature="function listUsers(req, res)",
                    start_line=1,
                    end_line=5,
                )
            ],
            imports=["const express = require('express')"],
        )
        content = "router.get('/users', auth, listUsers)\n"
        endpoint = {
            "method": "GET",
            "path": "/api/users",
            "handler": "listUsers",
            "file": rel_path,
            "route_file": rel_path,
            "handler_file": rel_path,
            "middleware": ["auth"],
            "request_body": "",
            "response_type": "",
            "framework": "express",
        }
        question = "Which express routes use auth middleware?"
        expected = ["express routes: GET /api/users -> listUsers", "middleware: auth"]
    elif framework == "fastify":
        rel_path = "src/routes/users.js"
        parsed = ParsedFile(
            path=Path(rel_path),
            language="javascript",
            symbols=[
                Symbol(
                    name="createUser",
                    kind="function",
                    signature="async function createUser(req, reply)",
                    start_line=1,
                    end_line=8,
                )
            ],
            imports=["const fastify = require('fastify')()"],
        )
        content = (
            "fastify.route({ method: 'POST', url: '/users', handler: createUser })\n"
        )
        endpoint = {
            "method": "POST",
            "path": "/api/users",
            "handler": "createUser",
            "file": rel_path,
            "route_file": rel_path,
            "handler_file": rel_path,
            "middleware": [],
            "request_body": "{ type: 'object' }",
            "response_type": "{ 201: { type: 'object' } }",
            "framework": "fastify",
        }
        question = "What fastify request and response schema does the users route use?"
        expected = [
            "fastify routes: POST /api/users -> createUser",
            "request bodies: { type: 'object' }",
            "response types: { 201: { type: 'object' } }",
        ]
    elif framework == "laravel":
        rel_path = "routes/web.php"
        parsed = ParsedFile(
            path=Path(rel_path),
            language="php",
            symbols=[
                Symbol(
                    name="orders",
                    kind="route",
                    signature="Route::post('/orders', [OrderController::class, 'store'])",
                    start_line=1,
                    end_line=1,
                )
            ],
            imports=[],
        )
        content = "Route::post('/orders', [OrderController::class, 'store'])->middleware(['auth']);\n"
        endpoint = {
            "method": "POST",
            "path": "/orders",
            "handler": "OrderController@store",
            "file": rel_path,
            "route_file": rel_path,
            "handler_file": "app/Http/Controllers/OrderController.php",
            "middleware": ["auth"],
            "request_body": "",
            "response_type": "",
            "framework": "laravel",
        }
        question = "Which laravel route uses auth middleware for orders?"
        expected = [
            "laravel routes: POST /orders -> OrderController@store",
            "middleware: auth",
        ]
    elif framework == "go":
        rel_path = "main.go"
        parsed = ParsedFile(
            path=Path(rel_path),
            language="go",
            symbols=[
                Symbol(
                    name="listUsers",
                    kind="function",
                    signature="func listUsers(c *gin.Context)",
                    start_line=1,
                    end_line=3,
                ),
                Symbol(
                    name="createUser",
                    kind="function",
                    signature="func createUser(c *gin.Context)",
                    start_line=4,
                    end_line=6,
                ),
            ],
            imports=['import "github.com/gin-gonic/gin"'],
        )
        content = 'admin.GET("/users", listUsers)\nadmin.POST("/users", createUser)\n'
        endpoint = {
            "method": "GET",
            "path": "/api/v1/admin/users",
            "handler": "listUsers",
            "file": rel_path,
            "route_file": rel_path,
            "handler_file": rel_path,
            "middleware": ["auth", "audit"],
            "request_body": "",
            "response_type": "",
            "framework": "go",
        }
        question = "Which go routes use auth and audit middleware for users?"
        expected = [
            "go routes: GET /api/v1/admin/users -> listUsers",
            "middleware: auth, audit",
        ]
    else:
        rel_path = "controllers/AuthController.py"
        parsed = ParsedFile(
            path=Path(rel_path),
            language="python",
            symbols=[
                Symbol(
                    name="Login",
                    kind="class",
                    signature="class Login",
                    start_line=1,
                    end_line=8,
                )
            ],
            imports=["import falcon"],
        )
        content = "class Login:\n    def on_post(self, req, res):\n        pass\n"
        endpoint = {
            "method": "POST",
            "path": "/api/v2/login",
            "handler": "AuthController.Login.on_post",
            "file": rel_path,
            "route_file": "main.py",
            "handler_file": rel_path,
            "middleware": [],
            "request_body": "",
            "response_type": "",
            "framework": "falcon",
        }
        question = "Which falcon login route is handled here?"
        expected = [
            "falcon routes: POST /api/v2/login -> AuthController.Login.on_post",
            "/api/v2/login",
        ]

    scan = RepoScan(
        file_tree={".": [rel_path]},
        file_summaries={rel_path: ""},
        api_endpoints=[endpoint],
        languages={parsed.language: 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[framework],
        entry_points=[],
        config_files=[],
        parsed_files={rel_path: parsed},
        file_contents={rel_path: content},
        source_kind_by_file={rel_path: "product"},
        file_frameworks={rel_path: [framework]},
    )
    return scan, expected, question


def _vue_scan() -> tuple[RepoScan, list[str], str]:
    rel_path = "src/components/UserList.vue"
    parsed = ParsedFile(
        path=Path(rel_path),
        language="vue",
        symbols=[
            Symbol(
                name="UserList",
                kind="component",
                signature="defineOptions({ name: 'UserList' })",
                start_line=1,
                end_line=30,
            ),
            Symbol(
                name="props",
                kind="constant",
                signature="defineProps()",
                props=["teamId"],
            ),
            Symbol(
                name="emit",
                kind="constant",
                signature="defineEmits()",
                fields=["select"],
            ),
            Symbol(name="router", kind="constant", signature="useRouter()"),
            Symbol(name="route", kind="constant", signature="useRoute()"),
            Symbol(name="pinia", kind="constant", signature="storeToRefs()"),
        ],
        imports=["from 'vue-router'", "from 'pinia'"],
    )
    content = "<script setup>const props = defineProps<{ teamId: string }>()</script>\n"
    scan = RepoScan(
        file_tree={".": [rel_path]},
        file_summaries={rel_path: ""},
        api_endpoints=[],
        languages={"vue": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=["vue"],
        entry_points=[],
        config_files=[],
        parsed_files={rel_path: parsed},
        file_contents={rel_path: content},
        source_kind_by_file={rel_path: "product"},
        file_frameworks={rel_path: ["vue"]},
    )
    return (
        scan,
        [
            "vue signals: router, route, pinia",
            "component props: teamId",
            "emits: select",
        ],
        "Which vue props, emit events, and pinia signals does this component use?",
    )


def _prompt_for_scan(tmp_path: Path, scan: RepoScan, question: str) -> str:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

    rel_paths = sorted(scan.file_contents.keys())
    plan = make_plan([make_bucket("App", "app", rel_paths)])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    code_records = build_code_chunks(scan, plan, {"chatbot": {"enabled": True}})
    relationship_records = build_relationship_chunks(
        scan, plan, {"chatbot": {"enabled": True}}
    )
    save_corpus(
        index_dir,
        "code",
        code_records,
        _KeywordEmbedClient().embed([record.text for record in code_records]),
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(
        index_dir,
        "relationship",
        relationship_records,
        _KeywordEmbedClient().embed([record.text for record in relationship_records]),
    )

    chat_client = _CapturingChatClient()
    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "rerank": False,
                "iterative_retrieval": False,
            },
        }
    }
    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_KeywordEmbedClient(),
        ),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=chat_client),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query(question)

    assert result["answer"] == "Grounded answer"
    assert chat_client.prompts
    return chat_client.prompts[-1]


@pytest.mark.parametrize(
    "framework", ["django", "express", "fastify", "laravel", "falcon", "go"]
)
def test_chatbot_eval_backend_framework_questions_surface_enriched_context(
    tmp_path: Path, framework: str
) -> None:
    scan, expected_fragments, question = _repo_scan_for_framework(framework)
    prompt = _prompt_for_scan(tmp_path, scan, question)

    for fragment in expected_fragments:
        assert fragment in prompt


def test_chatbot_eval_vue_questions_surface_component_signals(tmp_path: Path) -> None:
    scan, expected_fragments, question = _vue_scan()
    prompt = _prompt_for_scan(tmp_path, scan, question)

    for fragment in expected_fragments:
        assert fragment in prompt
