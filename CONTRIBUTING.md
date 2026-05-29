# Contributing to DeepDoc

Thanks for your interest in contributing. This guide covers everything you need: setting up locally, finding good first issues, writing code that fits the codebase, running tests, and getting your PR merged.

---

## Table of contents

- [Ways to contribute](#ways-to-contribute)
- [Local development setup](#local-development-setup)
- [Codebase orientation](#codebase-orientation)
- [Code style](#code-style)
- [Testing](#testing)
- [Submitting a pull request](#submitting-a-pull-request)
- [Release tracks](#release-tracks)
- [Release flow — Python package](#python-package-release-flow)
- [Release flow — VS Code extension](#vs-code-extension-release-flow)

---

## Ways to contribute

| Type | How |
|---|---|
| **Bug report** | Open a [GitHub issue](https://github.com/tss-pranavkumar/deepdoc/issues) with steps to reproduce, the command you ran, and the full error output. |
| **Feature request** | Open an issue describing the use case. Include a concrete example of what the output should look like. |
| **Code fix / feature** | Fork → branch → PR against `main`. Link the issue in your PR description. |
| **Documentation** | Same PR flow. Keep changes in sync with `README.md` and `CHANGELOG.md` if the behaviour changes. |
| **Tests** | Standalone test PRs are welcome, especially for edge cases and regression coverage. |

Before starting work on a large feature, open an issue first so we can discuss the design and avoid wasted effort.

---

## Local development setup

**Prerequisites:** Python 3.10+, Node 18+ (for building generated sites locally).

```bash
# 1. Fork and clone
git clone https://github.com/<you>/deepdoc.git
cd deepdoc

# 2. Create a virtual environment (use uv if available, or plain venv)
uv venv .venv && source .venv/bin/activate
# or: python3 -m venv .venv && source .venv/bin/activate

# 3. Install the package in editable mode with all extras
pip install -e ".[chatbot]"

# 4. Verify the install
python3 -m compileall deepdoc
python3 -m deepdoc.cli --help
```

To run generation against a real repo you need an LLM provider. The simplest approach is OpenAI:

```bash
export OPENAI_API_KEY=sk-...
deepdoc init          # creates .deepdoc.yaml in the current repo
deepdoc generate      # run full generation
```

Supported providers (via LiteLLM): OpenAI, Anthropic, Azure OpenAI, Gemini, any Ollama model. See `deepdoc config show` after `init`.

---

## Codebase orientation

DeepDoc is a five-phase pipeline. A high-level map of what lives where:

```
deepdoc/
  cli.py                     # Click entry-points (generate, update, serve, deploy …)
  pipeline_v2.py             # Orchestrates the five phases end-to-end
  config.py                  # .deepdoc.yaml loading and defaults

  planner/
    engine.py                # Scan entry-point + planning orchestration
    topology.py              # Call-graph-based domain clustering (no LLM)
    heuristics.py            # LLM planning steps (tests mock this)
    bucket_refinement.py     # Bucket decomposition / consolidation (canonical)
    nav_shaping.py           # Nav tree shaping (canonical)
    flow_candidates.py       # Execution path tracing
    specializations.py       # Database / runtime / flow bucket builders

  generator/
    generation.py            # Page generation engine + retry logic
    evidence.py              # Evidence pack assembly
    post_processors.py       # MDX repair pipeline (fence fixes, directive normalisation …)
    validation.py            # PageValidator — grounding, hallucination, route checks

  scanner/                   # Runtime, integration, artifact, database extraction
  parser/routes/             # Per-framework route detection
  chatbot/                   # Chatbot service, indexer, retrieval, FastAPI app
  site/builder/              # Fumadocs Next.js scaffold generators

tests/                       # pytest suite
vscode-extension/            # VS Code extension (separate release track)
web/                         # Marketing site (Vite + React)
```

The `CLAUDE.md` file in the root contains deeper architecture notes including the data model, key invariants, and rules about which files are canonical for specific responsibilities.

---

## Code style

- `from __future__ import annotations` at the top of every package module.
- Import order: stdlib → third-party → local (relative imports inside the package).
- 4-space indentation, PEP 8. No autoformatter is enforced — match the surrounding style.
- Type hints on new public functions. Use built-in generic forms (`dict[str, Any]`, `list[str]`) rather than `typing.Dict` / `typing.List`.
- `dataclass` for structured records.
- Naming: `snake_case` functions/variables, `PascalCase` classes, `UPPER_SNAKE_CASE` module-level constants.
- No speculative code. Only add what the PR actually needs.

When editing existing code: don't reformat adjacent lines, rename things that aren't broken, or add error handling for scenarios that can't happen. Touch only what you must.

---

## Testing

Run the suite with:

```bash
python3 -m pytest -q                                    # all tests
python3 -m pytest tests/test_state.py -q                # one file
python3 -m pytest -k "route or stale or chatbot" -q     # by expression
```

There is no enforced linter. `python3 -m compileall deepdoc` + pytest is the standard check.

### What to test

| Change area | Minimum expected coverage |
|---|---|
| Route detection / parser | Route-detector unit tests + at least one `scan_repo(...)` regression. |
| Planner / topology | Topology clustering unit tests + downstream bucket and nav behaviour. |
| Post-processors / MDX repair | Unit tests for the new function with representative inputs and edge cases (empty input, already-correct input, malformed input). |
| Freshness / smart update | Stale-detection tests + smart-update integration tests. |
| Chatbot / scaffold | `tests/test_fumadocs_builder.py` if scaffold output changed; chatbot config tests if service changed. |
| Generator / evidence | Mocked LLM tests for the generation path; evidence assembly for new bucket types. |

Tests that exercise LLM calls should mock `LLMClient.complete` (or the target function in `deepdoc/planner/heuristics.py` for planner tests). Do not make real API calls in tests.

### Test fixtures

Fixtures live in `tests/fixtures/`. If your test needs a fake repo or a pre-built plan, add a minimal fixture there rather than constructing large objects inline.

---

## Submitting a pull request

1. **Branch** off `main`. Use a descriptive name: `fix/mermaid-fence`, `feat/go-route-detection`, `docs/contributing`.
2. **Keep the diff small.** One logical change per PR. If you're fixing a bug and noticed unrelated dead code, mention it in the PR description but don't delete it in the same PR.
3. **Test your change.** Run the relevant test subset (see table above). New behaviour should have new tests.
4. **Update docs** if CLI behaviour changed: `README.md` and a `CHANGELOG.md` entry under `## Unreleased`.
5. **PR description** should answer:
   - What problem does this fix or what does it add?
   - How did you test it?
   - Any design decisions worth noting?
6. Maintainers aim to review within a few days. If you don't hear back in a week, ping on the issue.

### Important rules (from `CLAUDE.md`)

- Prefer extending `_v2` modules over creating new parallel flows.
- `_decompose_buckets` is canonical in `bucket_refinement.py` only — do not re-introduce duplicates elsewhere.
- `_normalize_nav_section` is canonical in `nav_shaping.py` only.
- Put repo-aware route fixes in `deepdoc/parser/routes/repo_resolver.py`, not planner code.
- If a change touches persisted state, audit plan, ledger, sync state, manifest, stale detection, and `_append_changelog` call sites together.
- `pipeline_v2._build_site()` must be called after `_record_changelog()`.
- CLI-facing failures should raise `click.ClickException` or print a clear Rich message.

---

## Release tracks

There are two independent release tracks. **Do not mix version numbers or changelog entries between them.**

| Track | Version file | Changelog | Workflow |
|---|---|---|---|
| Python package | `pyproject.toml` + `deepdoc/__init__.py` | `CHANGELOG.md` | `.github/workflows/release.yml` |
| VS Code extension | `vscode-extension/package.json` | `vscode-extension/CHANGELOG.md` | `.github/workflows/release-vscode-extension.yml` |

---

## Python package release flow

Releases are fully automated. When you push to `main`, the workflow checks whether the version in `pyproject.toml` already has a matching Git tag. If not, it builds and publishes to PyPI, creates the tag, and creates a GitHub Release using the matching section from `CHANGELOG.md`.

### Steps for each release

1. Update `version = "..."` in `pyproject.toml`.
2. Update `__version__ = "..."` in `deepdoc/__init__.py` to match.
3. Add a section to `CHANGELOG.md` (any of these heading styles work):
   ```md
   ## [1.2.3] - 2026-06-01

   ### Bug Fixes
   - Fixed X
   
   ### Features  
   - Added Y
   ```
4. Commit and push to `main`. The workflow does the rest.

### One-time PyPI setup (maintainers only)

1. On PyPI → `deepdoc` project → Publishing → add a Trusted Publisher:
   - Owner: `tss-pranavkumar`, repository: `deepdoc`, workflow: `release.yml`, environment: `pypi`
2. GitHub → Settings → Actions → General → Workflow permissions → `Read and write permissions`

---

## VS Code extension release flow

The extension workflow triggers when files under `vscode-extension/` change on `main`. It checks whether tag `vscode-extension-v<version>` exists, builds the extension, publishes to the Marketplace, and creates a GitHub Release.

### Steps for each release

1. Update `version` in `vscode-extension/package.json`.
2. Add a matching section to `vscode-extension/CHANGELOG.md`.
3. Commit and push to `main`.

### One-time Marketplace setup (maintainers only)

Create a VS Code Marketplace PAT with Manage scope for publisher `Pranawww` and add it as repo secret `VSCE_PAT` in GitHub → Settings → Secrets and variables → Actions.

---

## Questions?

Open an issue or reach out at `pranavdotdev@gmail.com`.
