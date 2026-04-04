# AGENTS.md
Guidance for coding agents working in this repository.

## Scope
- Applies to the repository root.
- Checked for Cursor rules in `.cursor/rules/` and `.cursorrules`: none found.
- Checked for Copilot rules in `.github/copilot-instructions.md`: none found.
- If you change core CLI behavior, persistence/state formats, routing semantics, or generated-site behavior, update this file in the same task.

## Repo Summary
- Project name: `deepdoc`
- Language/runtime: Python `>=3.10`
- Packaging: setuptools via `pyproject.toml`
- CLI entrypoint: `deepdoc = deepdoc.cli:main`
- Test runner: `pytest`
- Main implementation path is the v2 bucket-based pipeline.
- Generated docs usually live in `docs/`; the generated site lives in `site/`.

## Important Paths
- `pyproject.toml`: packaging, dependencies, pytest discovery
- `README.md`: user-facing behavior and documented workflows
- `deepdoc/cli.py`: Click commands, Rich output, serve/deploy flow
- `deepdoc/config.py`: defaults and `.deepdoc.yaml` helpers
- `deepdoc/pipeline_v2.py`: end-to-end orchestration
- `deepdoc/planner_v2.py`: scan model, bucket planning, endpoint ownership
- `deepdoc/generator_v2.py`: page generation, evidence assembly, validation
- `deepdoc/persistence_v2.py`: `.deepdoc/` state, plan, ledger, sync baseline
- `deepdoc/smart_update_v2.py`: incremental update and replan logic
- `deepdoc/parser/routes/`: route detection and repo-aware resolution
- `deepdoc/chatbot/` and `deepdoc/site/fumadocs_builder_v2.py`: chatbot and site scaffolding
- `tests/`: pytest suite and fixtures

## Architecture Notes
- Prefer extending `_v2` modules instead of creating new parallel flows.
- Keep `deepdoc/parser/api_detector.py` as a compatibility facade.
- Put repo-aware route fixes in `deepdoc/parser/routes/repo_resolver.py`, not planner code.
- Fix generated output by changing generators/builders, not by hand-editing `docs/`, `site/`, or `.deepdoc/` state.
- Preserve `source_kind` and `publication_tier` semantics consistently across planner, persistence, generation, smart update, and chatbot indexing.
- Published API docs should come from validated runtime endpoints via `RepoScan.published_api_endpoints`.
- If freshness/state semantics change, audit `planner_v2.py`, `generator_v2.py`, `persistence_v2.py`, and `smart_update_v2.py` together.
- If route behavior changes materially, update the engine fingerprint in `deepdoc/persistence_v2.py`.

## Generated And Derived Files
Treat these as generated or persisted outputs unless the task is specifically about their format:
- `.deepdoc/` contents and legacy files like `.deepdoc_plan.json` and `.deepdoc_file_map.json`
- `docs/`, `site/`, `site/public/`, and `site/out/`
- `build/`, `dist/`, `deepdoc.egg-info/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`
- Test fixture apps under `tests/fixtures/` unless the scenario explicitly requires fixture changes

## Install And Build Commands
Prefer `python3` over `python` in this repo.

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .
python3 -m pip install -e . pytest
python3 -m pip install -e ".[chatbot]"
python3 -m pip install build
python3 -m build
python3 -m deepdoc --help
python3 -m deepdoc.cli --help
deepdoc --help
```

If tree-sitter compilation is slow, the lighter fallback documented in `README.md` is:

```bash
python3 -m pip install click litellm gitpython rich pyyaml jinja2
python3 -m pip install -e . --no-deps
python3 -m pip install pytest
```

Useful runtime commands:

```bash
deepdoc init
deepdoc generate
deepdoc update
deepdoc serve --port 8001
deepdoc deploy
```

Notes:
- `deepdoc deploy` runs the generated Next/Fumadocs build and exports `site/out/`.
- `deepdoc serve` and `deepdoc deploy` assume generated site files already exist under `site/`.
- Avoid destructive generation modes like `deepdoc generate --clean --yes` unless the task explicitly requires a clean rebuild.

## Lint, Type Check, And Test Commands
- No formatter, linter, or type checker is configured in `pyproject.toml`.
- No checked-in config was found for `ruff`, `black`, `isort`, `flake8`, `mypy`, `pyright`, `tox`, or `nox`.
- Do not invent repo-standard lint or type-check commands unless the user explicitly asks for them.
- Practical verification here is `compileall`, CLI/import smoke checks, and pytest.

```bash
python3 -m compileall deepdoc
python3 -m pytest -q
python3 -m pytest tests/test_state.py -q
python3 -m pytest tests/test_state.py::test_save_and_load_sync_state_roundtrip -q
python3 -m pytest tests/test_smart_update.py -q
python3 -m pytest -k "route or stale or chatbot" -q
```

Single-test guidance:
- Run one file: `python3 -m pytest tests/test_state.py -q`
- Run one test: `python3 -m pytest tests/test_state.py::test_save_and_load_sync_state_roundtrip -q`
- Run by expression: `python3 -m pytest -k "baseline and not partial" -q`
- Use `-q` by default for focused runs.

## Testing Expectations
- For route work, run route-detector coverage plus at least one `scan_repo(...)` regression.
- For freshness or update work, run stale and smart-update tests, not just tiny helper tests.
- For chatbot or generated-site work, run chatbot config/scaffold/relationship tests and `tests/test_fumadocs_builder.py` if scaffold output changed.
- For non-trivial changes, prefer a focused test first, then `python3 -m pytest -q` if feasible.
- If you could not run verification, say so clearly and name the next command to run.

## Code Style

### Imports And Module Layout
- Start package modules with a short module docstring.
- Use `from __future__ import annotations` in package modules; that is the prevailing pattern.
- Group imports as standard library, third-party, then local package imports.
- Prefer relative imports inside the package when neighboring modules already do.
- Match existing section-divider comments and overall module structure where they already exist.

### Formatting And Structure
- Follow existing PEP 8 style with 4-space indentation.
- Match surrounding formatting; there is no enforced autoformatter.
- Prefer targeted changes over broad rewrites.
- Keep comments sparse and practical; explain non-obvious intent, not line-by-line mechanics.

### Types And Data Modeling
- Add type hints to new public functions and important helpers.
- Prefer built-in generics like `dict[str, Any]` and `list[str]`.
- Use dataclasses for structured records, matching `planner_v2.py`, `generator_v2.py`, and related scan models.
- Preserve compatibility fields and return shapes used across v1/v2 boundaries.

### Naming Conventions
- Use `snake_case` for functions, variables, and test names.
- Use `PascalCase` for classes and dataclasses.
- Use `UPPER_SNAKE_CASE` for module-level constants.
- Keep CLI option names and user-facing terms consistent with existing vocabulary: generate, update, serve, deploy, bucket, plan, ledger, sync state.

### Error Handling And UX
- CLI-facing failures should usually raise `click.ClickException` or print a clear Rich message.
- Rich console output via `Console`, `Panel`, and `Table` is the dominant CLI UX pattern.
- Broad `except Exception` blocks already exist around parsing, git, LLM, and persistence boundaries; if you catch broadly, return a safe fallback or preserve the last good state.
- Avoid silently swallowing actionable errors in core flows.

### Testing Style
- Tests use pytest with `test_*.py` discovery under `tests/`.
- Shared fixtures live in `tests/conftest.py`.
- Prefer focused regression tests near the changed behavior instead of adding large new fixture trees.

## Safe Workflow For Agents
- Read the relevant v2 modules before changing behavior; the same concept often spans planner, generator, persistence, and smart update.
- If a change touches persisted data or freshness semantics, audit plan save/load, ledger save/load, sync state save/load, manifest updates, and stale detection.
- If a change touches routing, audit the per-framework detector, route registry, repo resolver, `scan_repo(...)`, and endpoint bucket ownership.
- If a change touches chatbot behavior, audit `deepdoc/chatbot/settings.py`, `deepdoc/chatbot/indexer.py`, `deepdoc/chatbot/service.py`, `deepdoc/chatbot/scaffold.py`, and `deepdoc/site/fumadocs_builder_v2.py`.
- If you change documented CLI behavior, update `README.md` in the same task.
- This repo may be in a dirty worktree; inspect carefully and never revert unrelated user changes.

## Verification Defaults
- Good default checks are `python3 -m compileall deepdoc`, `python3 -m deepdoc.cli --help`, and targeted `python3 -m pytest ...` runs.
- Prefer the smallest command that exercises the edited area first.
