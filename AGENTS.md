# AGENTS.md

Guidance for coding agents working in this repository.
this is stale either update or dont read it 

## Scope
- Applies to the repository root: `/Users/apple/tss/codegen/codewiki`.
- No preexisting root `AGENTS.md` was present when this file was created.
- No Cursor rules were found in `.cursor/rules/` or `.cursorrules`.
- No Copilot rules were found in `.github/copilot-instructions.md`.
- Treat this file as the main repo-specific instruction source for agents.

## Repo Snapshot
- Project type: Python package plus CLI.
- Package name: `codewiki`.
- Python requirement: `>=3.10`.
- Packaging backend: setuptools via `pyproject.toml`.
- Console script: `codewiki = codewiki.cli:main`.
- Primary implementation path: bucket-based v2 pipeline.
- Legacy v1 modules still exist for compatibility and fallback behavior.

## Important Paths
- `pyproject.toml` - package metadata and entrypoint.
- `README.md` - user-facing command docs and workflow notes.
- `codewiki/cli.py` - Click commands and top-level UX.
- `codewiki/config.py` - default config and YAML load/save.
- `codewiki/pipeline_v2.py` - main v2 orchestration.
- `codewiki/planner_v2.py` - repo scan and bucket planning.
- `codewiki/generator_v2.py` - evidence assembly and page generation.
- `codewiki/persistence_v2.py` - `.codewiki/` state handling.
- `codewiki/updater_v2.py` - incremental refresh behavior.
- `codewiki/parser/` - registry plus language-specific parsers.
- `codewiki/llm/client.py` - LiteLLM wrapper.
- `codewiki/site/docusaurus_builder_v2.py` - Docusaurus config, sidebar, and theme asset generation.

## Install And Verify Commands
```bash
python -m pip install -e .
python -m pip install click litellm gitpython rich pyyaml jinja2
python -m pip install -e . --no-deps
codewiki --version
codewiki --help
python -m codewiki.cli --help
```

## Build, Generate, And Runtime Commands
```bash
python -m pip install build
python -m build
codewiki init
codewiki generate
codewiki generate --force
codewiki generate --clean --yes
codewiki update
codewiki update --replan
codewiki update --since HEAD~3
codewiki status
codewiki config show
codewiki config set llm.model gpt-4o
codewiki serve --port 3000
codewiki deploy
```

## Lint, Format, Type-Check, And Test Status
- No repo-configured lint, format, or type-check tool was found; there is no config for `ruff`, `black`, `isort`, `flake8`, `mypy`, `pyright`, `tox`, or `nox`.
- No checked-in automated test suite was found; there is no `tests/` directory and no `pytest` or `unittest` config.
- There is no current repo-native single-test command.
- Do not invent a repo-standard lint or test command unless the user asks you to add one.

## Smallest Useful Verification Commands
```bash
python -m compileall codewiki
python -m codewiki.cli --help
python -c "import codewiki; print(codewiki.__version__)"
```

If you add a pytest suite as part of a task, the normal single-test form should be:

```bash
python -m pytest tests/test_file.py::test_name -q
```

That command shape is conventional, but pytest is not currently preconfigured by this repo.

## Architecture Priorities
- Prefer the v2 bucket-based flow for new work.
- Treat v1 modules as legacy compatibility paths unless the task explicitly targets legacy behavior.
- If you touch behavior shared by both paths, preserve compatibility rather than deleting the older path casually.
- Follow the existing versioned naming convention: `_v2.py` modules and `V2` classes where appropriate.
- Parser architecture is layered: registry -> language parser -> `ParsedFile` / `Symbol` -> endpoint detection.
- Keep endpoint detection separate from syntax parsing.
- If you change CLI behavior, update `README.md` so command docs stay aligned.

## Generated And Derived Files
Treat these as outputs or persisted state; do not hand-edit them unless the task is explicitly about generated artifacts or state format changes.
- `.codewiki/`, `.codewiki/plan.json`, `.codewiki/scan_cache.json`, `.codewiki/ledger.json`, `.codewiki/file_map.json`
- `.codewiki_plan.json`, `.codewiki_file_map.json`, `.codewiki_manifest.json`
- `docs/`, `docusaurus.config.js`, `sidebars.js`, `package.json`, `node_modules/`, `build/`, `.docusaurus/`, `site/`, `codewiki.egg-info/`, `__pycache__/`
Do not treat `codewiki/planner.py.bak` as an authoritative source file.

## Code Style
### Imports And Module Layout
- Start modules with a concise module docstring.
- Use `from __future__ import annotations` at the top of normal Python modules.
- Group imports as standard library, third-party, then local package imports.
- Use direct relative imports inside the package, matching existing files.

### Formatting And Comments
- Follow existing PEP 8-ish formatting with 4-space indentation.
- Keep lines readable; the repo is not formatter-enforced.
- Large orchestration files often use divider comments; keep them when they improve navigation.
- Prefer small, descriptive helpers over large inline blocks when extending complex modules.
- Keep comments sparse and practical.

### Types And Data Modeling
- Add type hints to new public functions, methods, and constructors.
- Prefer modern built-in generics like `dict[str, Any]`, `list[str]`, and `set[str]`.
- Prefer `Path | None` and similar union syntax over `Optional[...]` unless matching nearby code.
- Use `Literal[...]` for small closed sets of string values when it helps clarity.
- Use `Any` at integration boundaries when exact typing would add noise.
- Use dataclasses for structured domain records, matching `DocBucket`, `DocPlan`, `RepoScan`, `ParsedFile`, and `Symbol`.

### Naming
- Modules and functions: `snake_case`.
- Classes and dataclasses: `PascalCase`.
- Constants: `UPPER_CASE`.
- Click commands should stay short and CLI-friendly.
- Keep bucket terminology consistent: `system`, `feature`, `endpoint`, `endpoint_ref`, `integration`, `database`.

## Error Handling And IO
- CLI-facing failures should usually raise `click.ClickException` or print a clear Rich message and exit.
- Library code usually degrades gracefully instead of crashing the whole pipeline.
- Preserve parser fallback behavior when tree-sitter is unavailable or parsing fails.
- Broad exception handling is already used at repo boundaries; if you catch broadly, return a safe fallback or re-raise with context.
- Prefer `pathlib.Path` for new code.
- Prefer `Path.read_text()` and `Path.write_text()` with `encoding="utf-8"`.
- When reading arbitrary repo files, use `errors="replace"` where the surrounding code does.
- Create parent directories with `mkdir(parents=True, exist_ok=True)`.
- Persist repo-relative paths as strings in saved plan or ledger data.

## Output And UX
- Use Rich for user-facing CLI output.
- Reuse a module-level `console = Console()` pattern when adding CLI or pipeline output.
- Prefer `Panel`, `Table`, and `Progress` for major workflow stages, matching the existing CLI.
- Avoid introducing the standard `logging` module for one-off status output unless you are making a broader logging change.

## Parser And Scan Guidance
- New language support should register through `codewiki/parser/registry.py`.
- Return `ParsedFile` objects with `symbols`, `imports`, and `raw_content` populated as consistently as practical.
- Keep endpoint detection separate from AST/syntax parsing logic.
- Preserve regex fallback behavior if tree-sitter-based parsing is unavailable.
- Be careful with performance in repo scans; current code scans whole repos and uses character budgets during generation.

## Editing Guidance For Agents
- Prefer minimal, targeted edits.
- Match surrounding style before introducing a new pattern.
- Do not add a new toolchain just because it is common elsewhere.
- Do not delete legacy code paths unless the task explicitly calls for cleanup.
- If you change persistence formats in `.codewiki/`, audit both save and load paths, including legacy compatibility files.
- If you modify docs-generation behavior, also check whether `README.md` examples or command descriptions need updates.

## Verification Expectations
- Because there is no enforced lint/test stack, do at least one narrow verification step for non-trivial Python changes.
- Prefer the smallest check that matches the edited area.
- Good defaults are `python -m compileall codewiki`, `python -m codewiki.cli --help`, and a targeted import smoke test.
