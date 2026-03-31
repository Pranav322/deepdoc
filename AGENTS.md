# AGENTS.md
Guidance for coding agents working in `/Users/apple/tss/codegen/codewiki`.

## Scope
- Applies to the repository root only.
- This is the primary repo-specific instruction file for agents.
- Checked for Cursor rules in `.cursor/rules/` and `.cursorrules`: none found.
- Checked for Copilot rules in `.github/copilot-instructions.md`: none found.
- If you change architecture, CLI flow, persistence semantics, or generated-site behavior, update this file in the same task.

## Repo Summary
- Python package with a Click CLI and a pytest suite.
- Package name: `codewiki`.
- Python requirement: `>=3.10`.
- Packaging backend: setuptools via `pyproject.toml`.
- Console entrypoint: `codewiki = codewiki.cli:main`.
- Main implementation path is the v2 bucket-based pipeline.
- Legacy v1 modules still exist for compatibility; do not remove them unless the task explicitly calls for migration or cleanup.
- Generated docs target `docs/` by default and the generated site lives under `site/`.

## Important Paths
- `pyproject.toml`: packaging, dependencies, pytest discovery.
- `README.md`: user-facing CLI behavior and workflows.
- `codewiki/cli.py`: commands, serve/deploy flow, Rich UX.
- `codewiki/config.py`: defaults and `.codewiki.yaml` helpers.
- `codewiki/pipeline_v2.py`: end-to-end scan/plan/generate/build orchestration.
- `codewiki/planner_v2.py`: scan model, bucket plan, endpoint ownership helpers.
- `codewiki/generator_v2.py`: page generation, validation, manifest updates.
- `codewiki/persistence_v2.py`: `.codewiki/` state, plan, ledger, sync baseline.
- `codewiki/smart_update_v2.py`: incremental update and replan logic.
- `codewiki/parser/routes/`: route detection and repo-aware route resolution.
- `codewiki/chatbot/`: chatbot config, indexing, scaffold generation.
- `codewiki/site/fumadocs_builder_v2.py`: generated Fumadocs scaffold.
- `tests/`: pytest suite and fixtures.

## Architecture Notes
- Prefer extending `_v2` modules over adding parallel flows.
- Keep `codewiki/parser/api_detector.py` as a compatibility facade.
- Repo-aware route fixes belong in `codewiki/parser/routes/repo_resolver.py`, not in planner code.
- Generated outputs should be fixed through generators/builders, not by hand-editing `docs/`, `site/`, or `.codewiki/` state.
- If freshness semantics change, audit `planner_v2.py`, `generator_v2.py`, `persistence_v2.py`, and `smart_update_v2.py` together.
- If persisted state changes, maintain save/load parity for both current and legacy compatibility files.
- If route behavior changes materially, update the engine fingerprint in `codewiki/persistence_v2.py`.

## Generated And Derived Files
Treat these as generated or persisted outputs unless the task is specifically about their format:
- `.codewiki/` contents and legacy compatibility files like `.codewiki_plan.json` and `.codewiki_file_map.json`
- `docs/`, `site/`, `site/public/`, and `site/out/`
- `build/`, `dist/`, `codewiki.egg-info/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`
- Test fixture apps under `tests/fixtures/` should only be edited when the scenario requires it

## Install And Build Commands
Prefer `python3` over `python` in this repo.

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .
python3 -m pip install -e . pytest
python3 -m pip install -e ".[chatbot]"
python3 -m pip install build
python3 -m build
python3 -m codewiki --help
python3 -m codewiki.cli --help
codewiki --help
```

If a full install is slow because of tree-sitter compilation, the lighter fallback documented in `README.md` is:

```bash
python3 -m pip install click litellm gitpython rich pyyaml jinja2
python3 -m pip install -e . --no-deps
python3 -m pip install pytest
```

Useful runtime commands:

```bash
codewiki init
codewiki generate
codewiki update
codewiki status
codewiki serve --port 8001
codewiki deploy
```

Notes:
- `codewiki deploy` runs the generated Next/Fumadocs build and export.
- `npx next build` only makes sense after generated site files exist under `site/`.
- Avoid destructive generation modes like `generate --clean --yes` unless the task explicitly requires a clean rebuild.

## Lint, Type Check, And Test Commands
- No formatter, linter, or type checker is configured in `pyproject.toml`.
- No checked-in config was found for `ruff`, `black`, `isort`, `flake8`, `mypy`, `pyright`, `tox`, or `nox`.
- Do not invent repo-standard lint/type commands unless the user explicitly asks for them.
- Practical verification here is `compileall`, CLI/import smoke checks, and pytest.

```bash
python3 -m compileall codewiki
python3 -m pytest
python3 -m pytest -q
python3 -m pytest tests/test_state.py -q
python3 -m pytest tests/test_state.py::test_save_and_load_sync_state_roundtrip -q
python3 -m pytest tests/test_smart_update.py -q
python3 -m pytest tests/test_framework_support.py -q
python3 -m pytest tests/test_chatbot_scaffold.py -q
python3 -m pytest -k "route or stale or chatbot" -q
```

Single-test guidance:
- Run one file: `python3 -m pytest tests/test_state.py -q`
- Run one test: `python3 -m pytest tests/test_state.py::test_save_and_load_sync_state_roundtrip -q`
- Filter by expression: `python3 -m pytest -k "baseline and not partial" -q`
- Use `-q` by default for focused runs.

## Testing Expectations
- For route work, run route detector coverage and at least one `scan_repo(...)` regression.
- For freshness or update work, run stale and smart-update tests, not just small helpers.
- For chatbot or generated-site config work, run chatbot config/scaffold tests and the Fumadocs builder tests if scaffold output changed.
- For non-trivial changes, prefer a focused test first, then `python3 -m pytest -q` if feasible.
- If you could not run verification, say so clearly and name the next command to run.

## Code Style

### Imports And Module Layout
- Start package modules with a short module docstring.
- Use `from __future__ import annotations` in package modules; this is the prevailing pattern.
- Group imports as standard library, third-party, then local package imports.
- Prefer relative imports inside the package when neighboring modules already do.
- Match the existing module structure with section-divider comments where they are already used.

### Formatting And Structure
- Follow existing PEP 8 style with 4-space indentation.
- Match surrounding formatting; there is no enforced autoformatter.
- Keep functions and helpers small when it improves clarity, but avoid needless abstraction.
- Prefer targeted changes over broad rewrites.
- Keep comments sparse and practical; explain non-obvious intent, not line-by-line mechanics.

### Types And Data Modeling
- Add type hints to new public functions and helpers.
- Prefer built-in generics like `dict[str, Any]` and `list[str]`.
- Use dataclasses for structured records, matching `planner_v2.py`, `generator_v2.py`, `scan_v2.py`, and route models.
- Use `Any` only at integration boundaries where stricter typing would add noise.
- Preserve compatibility fields and return shapes used across v1/v2 boundaries.

### Naming Conventions
- Use `snake_case` for functions, variables, and test names.
- Use `PascalCase` for classes and dataclasses.
- Use `UPPER_SNAKE_CASE` for module-level constants.
- Keep CLI option names and user-facing terms consistent with existing command vocabulary: generate, update, serve, deploy, bucket, plan, ledger, sync state.

### Error Handling And UX
- CLI-facing failures should usually raise `click.ClickException` or print a clear Rich message.
- Rich console output via `Console`, `Panel`, and `Table` is the dominant CLI UX pattern.
- Broad `except Exception` blocks already exist around parsing, git, LLM, and persistence boundaries; if you catch broadly, return a safe fallback or preserve the last good state.
- Avoid swallowing actionable errors silently in core flows.

### Testing Style
- Tests use pytest with `test_*.py` discovery under `tests/`.
- Shared fixtures live in `tests/conftest.py`.
- Existing tests often use real temporary git repos plus mocks at API or LLM boundaries; follow that pattern.
- Prefer focused regression tests near the changed behavior instead of large new fixture trees.

## Safe Workflow For Agents
- Read the relevant v2 modules before changing behavior; the same concept often spans planner, generator, persistence, and smart update.
- If a change touches persisted data or freshness semantics, audit plan save/load, ledger save/load, sync state save/load, manifest updates, and stale detection.
- If a change touches routing, audit the per-framework detector, route registry, repo resolver, `scan_repo(...)`, and endpoint bucket ownership.
- If a change touches chatbot behavior, audit `codewiki/chatbot/settings.py`, `codewiki/chatbot/scaffold.py`, `codewiki/site/fumadocs_builder_v2.py`, and `codewiki/cli.py`.
- If you change CLI behavior or documented commands, update `README.md` in the same task.
- This repo may be in a dirty worktree; inspect carefully and never revert unrelated user changes.

## Verification Defaults
- Good default checks are `python3 -m compileall codewiki`, `python3 -m codewiki.cli --help`, and targeted `python3 -m pytest ...` runs.
- Prefer the smallest command that exercises the edited area first.
