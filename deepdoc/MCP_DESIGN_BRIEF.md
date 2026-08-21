# DeepDoc MCP Server — Design Brief for Claude Code

> **Read this fully, then VERIFY every seam by opening the actual files.** Do not trust
> function names or signatures written here as gospel — they were captured from the current
> tree but the code is the source of truth. Where this brief says "verify", `grep`/read the
> real file and confirm the names, signatures, and return shapes before you write code.
> The repo has an exhaustive semantic map: **`deepdoc/CONCEPTS.md`** — use it for invariants
> and cross-file relationships you don't understand. Also read `AGENTS.md` at the repo root —
> it contains rules you must follow (including updating AGENTS.md/README.md if you change
> CLI behavior).

---

## Goal

Add an **MCP server** to DeepDoc so external AI clients (Claude Desktop, Cursor, etc.) can
search and retrieve a repo's generated documentation **and its underlying source code** —
mirroring what Mintlify does with its hosted search MCP server, but for DeepDoc's per-repo,
local corpus.

DeepDoc already owns the hard problem Mintlify's MCP solves: a hybrid retrieval backend
(FAISS + SQLite FTS + symbol/relationship chunks) plus a source archive that can read raw
code. **This task is an adapter over existing machinery, not new search infrastructure.**

---

## What already exists (the reuse seam — VERIFY each)

All under `deepdoc/chatbot/`. Read the files below and confirm before building.

| Concern | File / symbol | What to reuse |
|---|---|---|
| Query service (loads ALL corpora + vectors + source archive) | `chatbot/service.py` → `class ChatbotQueryService.__init__(repo_root, cfg)` | Instantiate one per repo; gives you `.query()`, `.deep()`, `.retrieve_context()`, and loaded `self.source_archive`, `self._docs_by_path`, etc. |
| Hybrid retrieval | `chatbot/retrieval_mixin.py` → `RetrievalMixin.retrieve_context(question, history, *, original_question, mode)` | Returns `code_hits`, `artifact_hits`, `doc_hits`, `relationship_hits` (RetrievedChunk objects with `.record` / `.score`). Backbone of the `search` MCP tool. |
| Grounded citation payload (already HTTP-shaped) | `chatbot/routes.py` → `/query-context` handler (lines ~189-253) | Shows exactly how the service turns hits into `code_citations`, `doc_citations`, `doc_links`. Reuse this shaping for MCP tool output. |
| Read a raw source file | `chatbot/deep_research.py` → `DeepResearcher._execute_tool(...)` `action == "read_file"` (line ~632) | The canonical `read_file` implementation reading from `service.source_archive[path]` with `start`/`end` line slicing + the `--- path (lines a-b) ---` format. REUSE this exact logic for an MCP `read_source_file` tool. |
| Grep over source | same `_execute_tool`, `action == "grep"` (line ~653) | Canonical regex grep over archived source. REUSE for an MCP `grep` tool. |
| Filesystem browse over docs | `chatbot/persistence.py` (doc corpora) + `ChatbotQueryService._docs_by_path` / `_docs_by_url` | Mintlify's "query docs filesystem". Navigate/read generated doc pages and source paths. |
| Canonical "which file paths are real" | `chatbot/persistence.py` → `load_source_catalog(index_dir)`; `ChatbotQueryService.source_catalog` | Let MCP tools reject hallucinated paths and list the file tree. |
| Config / defaults | `chatbot/settings.py` → `get_chatbot_cfg(cfg)`, `chatbot_index_dir(repo_root, cfg)`, `chatbot_backend_port(...)` | Resolve where the `.deepdoc/chatbot` index lives and port conventions. |
| **Ops / write path** (SEPARATE, phase 2) | `smart_update_v2.py` → `class SmartUpdater(repo_root, cfg).update(since="HEAD~1", force_replan=False)` | Returns stats dict (pages_updated, strategy, ...). This is the `update_docs` tool seam. **Do not wire the write path in this first build** unless the brief says so. |
| CLI wiring (how commands are added) | `cli.py` → Click `@click.group` `main`; commands via `@main.command(...)`; helpers `_load_or_exit()` (~1385), `_find_repo_root()` (~1469), `_start_chatbot_backend()` (~1618) | Follow the existing command pattern. Reuse `_load_or_exit` + `_find_repo_root`. |
| Dependencies | repo-root `pyproject.toml` → `[project.optional-dependencies] chatbot = [...]` | Add the official `mcp` Python SDK here (see "Dependencies" below). |
| Tests | `tests/test_chatbot_query.py`, `tests/test_chatbot_persistence.py`, `tests/test_cli_*.py` | Match existing test style/mocks (unit tests mock at `deepdoc.chatbot.service` / `similarity_search`). |

> **VERIFY the CLI:** `cli.py` hosts the chatbot backend as a subprocess via `uvicorn chatbot_backend.app:app`
> from the generated `chatbot_backend/` scaffold (`scaffold.py`). You have TWO viable transports and must pick
> one per the Decision below — read `chatbot/scaffold.py` and `_start_chatbot_backend()` to understand the
> existing serve pattern before choosing.

---

## Scope

### In scope (Phase 1 — docs-search MCP, read-only)
1. A new module that exposes an MCP server with **read/search tools only**:
   - `search(query)` → grounded chunks + citations (reuse `retrieve_context` + route-shaping).
   - `read_source_file(path, start_line, end_line)` → reuse the DeepResearcher `_execute_tool` read_file logic.
   - `grep(pattern)` → reuse the DeepResearcher grep logic.
   - `read_docs(path)` / `list_docs(root="")` → browse generated doc pages (query the docs filesystem).
2. A new CLI command to launch it (see Decisions).
3. Unit tests for each tool, mocked the way existing chatbot tests do.
4. Wire the `mcp` dependency into `pyproject.toml`.

### Out of scope (Phase 2 — do NOT build now)
- The `update_docs` write/ops tool (SmartUpdater).
- Auth / multi-tenant hosting / remote endpoint.
- Anything that changes the pipeline, plan, or generated-site behavior.

> If the user approves Phase 2 later, the `update_docs` MCP tool will call
> `SmartUpdater(repo_root, cfg).update(...)`. Keep the module structured so that's an easy add.

---

## Decisions to confirm with the user (or pick the recommended default and note it)

### Dev 1 — MCP transport
- **Recommended:** **stdio** via the official `mcp` Python SDK (`mcp.server.FastMCP` / `Server`).
  Simplest for Claude Desktop / `claude mcp add`, zero port/auth management, matches DeepDoc's
  per-repo local model. Server constructed lazily or per-repo; corpus load happens once per process.
- Alternative: SSE/`streamable-http` on the existing uvicorn port. More moving parts; only if the user
  explicitly wants a network endpoint. **Default to stdio.**

### Dev 2 — How the server finds its repo
- **Recommended:** a `deepdoc mcp serve` command that runs in the CWD and auto-discovers the repo
  root + `.deepdoc.yaml` via the existing `_find_repo_root()` / `_load_or_exit()` helpers, then
  prints the `claude mcp add` command to the user.
- Register with something like: `claude mcp add -s local deepdoc -- deepdoc mcp serve`
  (verify the exact syntax against `claude mcp add --help` / the claude-code skill).

---

## Implementation plan

### Task 1 — Add the MCP dependency
- Edit repo-root `pyproject.toml`, `chatbot` optional-dependencies: add `mcp>=1.0` (check latest).
- Run `pip install -e ".[chatbot]"` (or your active venv equivalent) and confirm `import mcp` works.

### Task 2 — New module: `deepdoc/chatbot/mcp_server.py`
- `def create_mcp_server(repo_root: Path, cfg: dict[str, Any] | None = None) -> mcp.server.Server`
  - Resolve cfg via `get_chatbot_cfg` if not given (VERIFY the exact loader name in `config.py`).
  - Lazy-construct `ChatbotQueryService(repo_root, cfg)` on first tool call (index load is heavy).
  - Register tools with `@server.tool(...)` syntax from the `mcp` SDK.
- Each tool maps to the reuse seam in the table above. **Copy the read_file/grep bodies from
  `deep_research.py` rather than reimplementing.** Return structured text/Markdown the way the
  existing routes/answer mixin shape citations.
- Guard: if the corpus/index is empty/unbuilt, return a clear message telling the user to run
  `deepdoc generate` / `deepdoc update` (with chatbot enabled), mirroring the existing warning in
  `ChatbotQueryService.__init__`.

### Task 3 — CLI command in `cli.py`
- Add a `deepdoc mcp serve` command (VERIFY whether the project prefers `@main.command` groups;
  follow `_start_chatbot_backend` for a long-running subprocess pattern, but a simple
  `mcp.server.stdio.run()`/`FastMCP.run()` in the foreground is fine).
- Reuse `_load_or_exit()` and `_find_repo_root()`.
- Print human-readable startup info + the exact connect command for the client.

### Task 4 — Tests
- New `tests/test_chatbot_mcp.py` (confirm naming convention from existing files).
- Mock at the same seams the chatbot tests use (e.g. monkeypatch `similarity_search`,
  construct the service with a tiny fake index). Test each tool's happy path + error path
  (empty corpus, missing file, bad line range, short grep pattern).
- Run: `python3 -m pytest -q` and the new file specifically.

### Task 5 — Docs + AGENTS.md compliance
- Per AGENTS.md: if you changed CLI behavior (you added a command), update `AGENTS.md` **and**
  `README.md` to include `deepdoc mcp serve`.
- Update the module docstring / package structure notes if `deepdoc/chatbot/mcp_server.py` is new.

---

## Verification (must do, don't skip)

1. `claude auth status` → confirm logged in (or tell the user to `claude auth login`
   interactively — you cannot do browser OAuth yourself).
2. `python3 -m pytest -q` → all tests pass (existing + new).
3. Manual smoke test the MCP server on a repo that already has `deepdoc generate` run with the
   chatbot enabled, so the index + source archive exist:
   - Run `deepdoc mcp serve` from that repo.
   - Drive it over stdio with a small JSON-RPC payload, or connect via `claude mcp add` +
     a Claude session, and call `search` / `read_source_file` / `grep`.
   - Confirm a real (non-hallucinated) file/citation comes back.
4. Confirm `import mcp` in the target venv.

---

## Please report back
- Which transport + module layout you chose (state your default if not overridden).
- The exact list of files created/changed.
- Any discrepancy between this brief and the actual code you found (names, signatures,
  config loader, path layout) — flag it, don't silently "fix" it.
- Test output summary.