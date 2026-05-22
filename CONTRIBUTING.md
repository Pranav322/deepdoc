# Contributing to DeepDoc

Thanks for your interest in DeepDoc. This document covers contributor-facing topics: running locally, testing, and the release flow for both the Python package and the VS Code extension.

For user-facing docs (how to run DeepDoc against your project), see [README.md](./README.md).

---

## Running tests

DeepDoc uses `pytest`. No formatter or linter is configured — the standard verification loop is `compileall` + `pytest`.

```bash
python3 -m pip install -e ".[chatbot]"          # install with chatbot extras
python3 -m compileall deepdoc                   # syntax check
python3 -m pytest -q                            # full suite
python3 -m pytest tests/test_state.py -q        # one file
python3 -m pytest -k "route or stale" -q        # by expression
```

The MDX compile-gate tests require Node 18+ on `PATH`; they spawn `node validate.mjs` for the validator integration cases. Tests that exercise generation behavior mock `LLMClient.complete`.

## Repo layout

```
deepdoc/                        # the Python package
  cli.py                        # Click commands
  pipeline_v2.py                # 5-phase orchestration
  planner/                      # scan + bucket planning
  generator/                    # generation, validation, MDX compile gate
    mdx_validator/              # Node helper (validate.mjs + package.json)
    mdx_compile_gate.py         # gate orchestrator + JSX-strip fallback
    post_processors.py          # legacy MDX hazard fixers (belt-and-suspenders)
  chatbot/                      # service + indexer + scaffold for the chatbot
  site/builder/                 # scaffolds the Fumadocs Next.js site
  prompts/                      # all LLM prompt strings
tests/                          # pytest suite + fixtures
vscode-extension/               # separate release track
```

See [`CLAUDE.md`](./CLAUDE.md) for deeper architectural notes when working inside the codebase.

---

## Release tracks

This repository has two independent release tracks:

- **Python package (`deepdoc`)** — controlled by `pyproject.toml`, root `CHANGELOG.md`, and `.github/workflows/release.yml`.
- **VS Code extension (`vscode-extension/`)** — controlled by `vscode-extension/package.json`, `vscode-extension/CHANGELOG.md`, and `.github/workflows/release-vscode-extension.yml`.

Keep versions and changelog entries separated by track.

---

## Python package release flow

### What happens automatically

When you push to `main`, the release workflow checks the version in `pyproject.toml`.
If that version does not already have a matching Git tag like `v0.1.1`, GitHub Actions will:

- build the package
- publish it to PyPI
- create the Git tag
- create a GitHub Release and attach the built files
- use the matching section from `CHANGELOG.md` as the release notes when present

### Your release flow

1. Update `version = "..."` in `pyproject.toml`
2. Update `__version__ = "..."` in `deepdoc/__init__.py`
3. Add a matching section to `CHANGELOG.md`
4. Commit your changes
5. Push to `main`

That is it. You do not need to manually create tags or GitHub Releases.

### Changelog format

The release workflow looks for a section in `CHANGELOG.md` that matches the version in `pyproject.toml`.
These heading styles all work:

- `## 0.1.2`
- `## [0.1.2]`
- `## v0.1.2`
- `## [0.1.2] - 2026-04-03`

Example:

```md
## [0.1.2] - 2026-04-03

- Added automated GitHub releases
- Improved PyPI metadata
- Documented `deepdoc[chatbot]` installation
```

If the matching version section is missing, GitHub falls back to auto-generated release notes.

### One-time setup

1. On PyPI, open the `deepdoc` project
2. Go to `Publishing`
3. Add a Trusted Publisher for GitHub Actions with:
   - owner: `tss-pranavkumar`
   - repository: `deepdoc`
   - workflow filename: `release.yml`
   - environment name: `pypi`
4. In GitHub, open Settings → Actions → General
5. Set Workflow permissions to `Read and write permissions`

After that, every new version pushed to `main` can publish without a PyPI token.

---

## VS Code extension release flow

The VS Code extension release is automated from `main` when files under `vscode-extension/` change.

What the extension workflow does:

- reads `vscode-extension/package.json` version
- checks whether tag `vscode-extension-v<version>` already exists
- builds and packages the extension
- publishes to Marketplace using `VSCE_PAT`
- creates and pushes the matching git tag
- creates a GitHub release with notes from `vscode-extension/CHANGELOG.md` (fallback to generated notes)

### One-time setup for extension publishing

1. Create a VS Code Marketplace PAT with Manage scope for publisher `Pranawww`
2. Add repo secret `VSCE_PAT` in GitHub Actions secrets

### Extension release flow on each version

1. Update `vscode-extension/package.json` version
2. Add matching section to `vscode-extension/CHANGELOG.md`
3. Commit and push to `main`
