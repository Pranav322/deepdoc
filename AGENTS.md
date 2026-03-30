# AGENTS.md

Guidance for coding agents working in `/Users/apple/tss/codegen/codewiki`.

## Scope
- Applies to the repository root only.
- This file replaces the earlier stale root `AGENTS.md`.
- No Cursor rules were found in `.cursor/rules/` or `.cursorrules`.
- No Copilot rules were found in `.github/copilot-instructions.md`.
- Treat this file as the primary repo-specific instruction source for agents.

## Repo Snapshot
- Python package with a Click CLI and pytest suite.
- Package name: `codewiki`; Python requirement: `>=3.10`.
- Packaging backend: setuptools via `pyproject.toml`.
- Console entrypoint: `codewiki = codewiki.cli:main`.
- Main implementation path: the v2 bucket-based planner/generator pipeline.
- Legacy v1 modules still exist; preserve compatibility unless cleanup is the explicit task.
- Site generation now targets a generated Fumadocs app, not the older Mintlify site layer.

## Important Paths
- `pyproject.toml` - package metadata and pytest discovery config.
- `README.md` - user-facing CLI docs and workflow notes.
- `codewiki/cli.py` - Click commands and top-level UX.
- `codewiki/config.py` - default config and YAML load/save helpers.
- `codewiki/pipeline_v2.py` - main scan/plan/generate/build orchestration.
- `codewiki/planner_v2.py` - repo scan and bucket planning logic.
- `codewiki/generator_v2.py` - page generation and manifest updates.
- `codewiki/persistence_v2.py` - `.codewiki/` state persistence.
- `codewiki/parser/` - parser registry and language-specific parsers.
- `codewiki/site/fumadocs_builder_v2.py` - generated Fumadocs site scaffold/page-tree generation.
- `tests/` - pytest suite, fixtures, and regression coverage.

## Install And Build Commands
```bash
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install -e . pytest
python -m pip install build
python -m build
codewiki --help
python -m codewiki --help
python -m codewiki.cli --help
```
If tree-sitter builds are slow locally, the README-supported fallback is:
```bash
python -m pip install click litellm gitpython rich pyyaml jinja2
python -m pip install -e . --no-deps
python -m pip install pytest
```
Useful runtime commands once the package is installed:
```bash
codewiki init
codewiki generate
codewiki update
codewiki serve --port 3000
npx next build
```

`python -m build` is the packaging build. `npx next build` only makes sense after docs/site files exist. Avoid `codewiki deploy` unless deployment is explicitly requested.

## Lint, Type-Check, And Test Commands
- There is no repo-configured formatter, linter, or type checker in `pyproject.toml`.
- There is no checked-in config for `ruff`, `black`, `isort`, `flake8`, `mypy`, `pyright`, `tox`, or `nox`.
- Do not invent a new lint/type-check command unless the user asks for that tooling.
- The practical verification stack here is `compileall`, CLI/import smoke checks, and pytest.

Useful commands:
```bash
python -m compileall codewiki
python -m pytest
python -m pytest tests/test_state.py
python -m pytest tests/test_state.py::test_save_and_load_sync_state_roundtrip -q
python -m pytest -k baseline -q
```
Single-test guidance:
- File: `python -m pytest tests/test_state.py`
- Test node: `python -m pytest tests/test_state.py::test_name -q`
- Keyword filter: `python -m pytest -k "search_term" -q`
CI currently runs:
```bash
python -m pip install -e . pytest
python -m compileall codewiki
python -m pytest
```

## Architecture Priorities
- Prefer the v2 flow in `codewiki/pipeline_v2.py`, `codewiki/planner_v2.py`, and related `_v2` modules.
- Treat `planner.py` and other v1-era modules as compatibility paths, not the default extension point.
- Keep bucket terminology consistent: `system`, `feature`, `endpoint`, `endpoint_ref`, `integration`, `database`.
- Keep parser responsibilities layered: registry -> language parser -> parsed symbols/imports -> endpoint detection.
- Preserve incremental-update and persisted-state behavior when changing planning or generation logic.
- If you change CLI behavior or documented commands, update `README.md` to match.

## Generated And Derived Files
Treat these as generated outputs or persisted state; do not hand-edit them unless the task is specifically about their format or generation logic.
- `.codewiki/` contents, sync state, and legacy compatibility outputs like `.codewiki_plan.json` and `.codewiki_file_map.json`.
- Generated docs/site artifacts such as `docs/`, `site/`, and `site/public/`.
- Build/cache directories such as `build/`, `dist/`, `codewiki.egg-info/`, `__pycache__/`, `.pytest_cache/`, and `.ruff_cache/`.
- Test fixture apps under `tests/fixtures/` are intentional fixtures; edit them only when the test scenario requires it.
## Code Style
### Imports And Module Layout
- Start Python modules with a short module docstring.
- Use `from __future__ import annotations` in normal package modules; this is the dominant pattern.
- Group imports as standard library, third-party, then local package imports.
- Use relative imports inside the package when matching surrounding code.

### Formatting And Structure
- Follow existing PEP 8-ish formatting with 4-space indentation.
- Match surrounding style; there is no enforced formatter.
- Preserve useful divider comments in large orchestration modules.
- Keep comments sparse and practical.

### Types And Data Modeling
- Add type hints to new public functions, methods, and constructors.
- Prefer built-in generics like `dict[str, Any]` and `list[str]`.
- Prefer `Path | None` style unions over `Optional[...]` unless nearby code uses the older form.
- Use `Literal[...]` for narrow string domains when it clarifies behavior.
- Use dataclasses for structured records, matching models like `DocBucket`, `DocPlan`, `RepoScan`, `ParsedFile`, and `Symbol`.
- Use `Any` at integration boundaries where exact typing would add noise.

### Naming Conventions
- Functions, variables, and modules: `snake_case`.
- Classes and dataclasses: `PascalCase`.
- Constants: `UPPER_CASE`.
- Follow the repository's versioned naming convention for major flows: `_v2.py` modules and `V2` class names.

### Error Handling And UX
- CLI-facing failures should usually raise `click.ClickException` or present a clear Rich message.
- Use Rich for user-facing output; the common pattern is a module-level `console = Console()`.
- Broad `except Exception` blocks already exist around parsing, git, and persistence boundaries; if you catch broadly, return a safe fallback or re-raise with context.
- Avoid introducing the standard `logging` module for one-off CLI status output unless making a broader logging change.

### Paths, Files, And Persistence
- Prefer `pathlib.Path` for new file-system code.
- Use `Path.read_text()` and `Path.write_text()` with `encoding="utf-8"`.
- When reading arbitrary repo files, prefer `errors="replace"` because the codebase already does this in scan/generation paths.
- Create parent directories with `mkdir(parents=True, exist_ok=True)`.
- Persist repo-relative paths as strings in saved manifests, plans, ledgers, and related state.

## Testing Conventions
- The suite uses pytest and is discovered from `tests/` via `pyproject.toml`.
- Test modules and functions follow the configured `test_*.py` and `test_*` naming.
- Shared fixtures live in `tests/conftest.py`.
- Existing tests prefer real temporary git repositories when diff semantics matter.
- Mock LLM boundaries rather than deeply mocking every internal helper around planning or generation.

## Editing Guidance For Agents
- Prefer minimal, targeted edits.
- Match surrounding style before introducing a new pattern.
- Do not delete legacy compatibility code unless the task clearly calls for it.
- If you change persisted state formats, audit both save and load paths, including legacy compatibility files.
- If you change Fumadocs build behavior, review both the builder module and CLI commands that invoke `next`.
- If you change user-visible CLI flows, examples, or defaults, update `README.md` in the same task.

## Verification Expectations
- For non-trivial Python changes, run at least one narrow verification step.
- Prefer the smallest command that exercises the edited area: `python -m compileall codewiki`, `python -m codewiki.cli --help`, `python -c "import codewiki; print(codewiki.__version__)"`, or a targeted `python -m pytest ...` invocation.
- If you could not run verification, say so explicitly and provide the exact command to run next.
