<div align="center">
  <img src="./web/public/favicon.svg" alt="DeepDoc" width="96" height="96" />
  <h1>DeepDoc</h1>
  <p><b>Documentation that keeps pace with your codebase.</b></p>
  <p>DeepDoc reads your repository and writes a docs site with a chatbot that cites real files, then regenerates only the pages your commits touch.</p>

  [![PyPI version](https://img.shields.io/pypi/v/deepdoc)](https://pypi.org/project/deepdoc/)
  [![Python versions](https://img.shields.io/pypi/pyversions/deepdoc)](https://pypi.org/project/deepdoc/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

  <a href="https://deepdoc.tech/docs"><b>Docs</b></a> ·
  <a href="https://cloud.deepdoc.tech"><b>Try it in the browser</b></a> ·
  <a href="https://deepdoc.tech/changelog"><b>Changelog</b></a>
</div>

<br/>

## Quick start

You need Python 3.10+ and Node.js 18+.

```bash
pip install deepdoc
cd your-project
deepdoc init --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-...
deepdoc generate
deepdoc serve          # http://localhost:3000
```

No install? [cloud.deepdoc.tech](https://cloud.deepdoc.tech) runs the same generator: sign in with GitHub, pick a repository (private ones too), get a docs site. Sites are private by default.

## What you get

- **Docs organised the way readers look.** Architecture, endpoints, integrations and schemas grouped by domain, not one noisy page per file.
- **Answers that cite real files.** An optional chatbot ships with the site. Every answer points to a file path and line range, in a fast mode or a deeper research mode.
- **Updates that touch only what changed.** `deepdoc update` diffs against the last synced commit and regenerates only the affected pages.
- **Theming that costs nothing.** Colours, logo, fonts, layout and navigation are re-applied from your saved plan on `deepdoc serve`, with no regeneration and no LLM calls.
- **A quality gate.** `deepdoc deploy` refuses to publish pages that failed validation.

## Commands

| Command | What it does | Calls an LLM |
|---|---|---|
| `deepdoc init` | Write `.deepdoc.yaml` | No |
| `deepdoc generate` | Scan, plan and write the docs | Yes |
| `deepdoc update` | Refresh docs after code changes | Yes, for changed pages |
| `deepdoc serve` | Preview locally with live reload | No |
| `deepdoc deploy` | Build a static site into `deepdoc-site/out/` | No |
| `deepdoc status` | Show what exists and what is stale | No |
| `deepdoc config show\|set` | Read or write config values | No |
| `deepdoc performance` | Timing and token metrics for recent runs | No |
| `deepdoc clean` | Remove what DeepDoc created | No |
| `deepdoc benchmark` | Score planner quality | Depends |

Every flag is documented in [Commands](https://deepdoc.tech/docs/commands).

## Providers

`--provider` accepts `anthropic`, `openai`, `azure`, `ollama`, or any [LiteLLM](https://docs.litellm.ai/docs/providers) alias such as `gemini` or `groq`. Ollama runs fully local with no API key. See [Providers](https://deepdoc.tech/docs/providers) for each provider's key, model and Azure requirements.

## Supported stacks

Endpoint, runtime and call-graph analysis cover:

| Language | Frameworks |
|---|---|
| Python | Django, Django REST Framework, FastAPI, Falcon |
| JavaScript / TypeScript | Express, Fastify, NestJS |
| PHP | Laravel |
| Go | `net/http` and common routers |
| Vue | Components and symbols |

Other languages may parse, but are not fully supported. DeepDoc prints a warning when it finds source it cannot analyse.

## Chatbot

Off by default. Enable it with `deepdoc init --with-chatbot` or `deepdoc config set chatbot.enabled true`, install the extra, and `deepdoc serve` starts the backend next to the site:

```bash
pip install "deepdoc[chatbot]"
```

Embeddings default to a local `fastembed` model, so one API key is usually enough. See [Chatbot](https://deepdoc.tech/docs/chatbot) for modes, models and deployment.

## Keep docs current in CI

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0          # update needs history to diff against
- run: pip install deepdoc
- run: deepdoc update --strict-quality
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

[`examples/deepdoc-refresh.yml`](./examples/deepdoc-refresh.yml) is a complete workflow. Commit `.deepdoc.yaml` and `.deepdoc/`: the saved plan is what makes theming and updates cheap.

## Repository layout

| Path | What it is |
|---|---|
| [`deepdoc/`](./deepdoc/) | The Python package: CLI, scanner, planner, generator, chatbot and site builder |
| [`web/`](./web/) | deepdoc.tech, its product docs and the hosted app, one Astro project |
| [`vscode-extension/`](./vscode-extension/) | Explain selected code in Fast or Deep mode and insert comments inline |
| [`hosted-runner/`](./hosted-runner/) | The container that generates docs for DeepDoc Cloud |
| [`tests/`](./tests/) | The pytest suite: `python3 -m pytest -q` |

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for local setup, code style, testing and the release flow. Agents working in this repository should read [AGENTS.md](./AGENTS.md).

## License

MIT
