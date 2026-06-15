# DeepDoc — Session Handoff

**Branch:** `main` — 5 commits ahead of origin  
**Last commits:** `8ff67b5` (chatbot fix) ← `6a19214` (Next.js migration)

---

## What Was Built

### 1. MkDocs → Next.js + Fumadocs site builder

The static documentation site now generates a **Next.js 15 + Fumadocs** shell instead of MkDocs Material. Root cause of the switch: MkDocs was the second migration — the original Fumadocs build kept crashing because LLM-generated content with `{`, `<`, or unbalanced fences broke the MDX compiler. The fix was routing content through `remark/rehype` at runtime (not the JSX compiler), which makes bad LLM syntax render as escaped text instead of a build crash.

**Builder entry point:** `deepdoc/site/builder/next_builder.py` → `build_next_from_plan()`  
**Template:** `deepdoc/site/builder/next_template/` (shipped as package data)

What the builder writes into `{repo}/site/`:
```
deepdoc.config.json     ← project name, brand colors, chatbot URL, nav tree,
                           commit SHA, generation date
content/docs/           ← symlink/copy of docs/*.md
app/                    ← copied from next_template (Next.js shell)
components/
lib/
…
```

### 2. Next.js template structure

```
app/
  layout.tsx                    root: <html>, brand CSS vars, mermaid, __DD_CONFIG__
  globals.css
  (main)/
    layout.tsx                  DocsLayout + ChatbotWidget + sidebar footer (gen meta)
    [[...slug]]/page.tsx        dynamic doc page — reads .md via lib/docs.ts
  ask/
    layout.tsx                  pass-through (no Fumadocs sidebar)
    page.tsx                    two-pane chatbot workspace
components/
  chatbot.tsx                   bottom-fixed ask bar (hides on /ask)
lib/
  config.ts                     DeepDocConfig interface + getConfig()
  nav.ts                        deepdoc.config.json → Fumadocs PageTree
  docs.ts                       remark pipeline: reads .md, renders HTML server-side
```

**Route groups** — `app/(main)/` has DocsLayout; `app/ask/` is standalone. Both share the root layout (`<html>`, brand vars, scripts). This is why `/ask` has no sidebar without any conditional logic.

**Content rendering** — `lib/docs.ts` runs a remark → rehype pipeline (GFM, slug, shiki syntax highlight). No MDX compiler involved. A `{` in LLM output renders as literal text.

**Brand colors** — written into `deepdoc.config.json` as `colors.{primary,light,dark}`, injected as CSS vars `--brand`, `--brand-light`, `--brand-dark` in root layout.

**Chatbot bar positioning** — uses Fumadocs CSS vars so it sits exactly over the content column on every screen size:
```css
left: calc(var(--fd-layout-offset, 0px) + var(--fd-sidebar-width, 0px));
right: var(--fd-toc-width, 0px);
```

### 3. /ask page (two-pane chatbot workspace)

- **Left pane** — conversation thread. Each turn shows question bubble + streamed answer. During deep mode, research trace steps stream inline below the answer (dashed separator) and are erased when the turn completes.
- **Right pane** — sources panel. Shows evidence (file path, line range, snippet) and references for both fast and deep mode. Shows "Researching…" / "Gathering sources…" while pending.
- **Ask bar** — centred card at bottom, max-width 760px (matches docs content width), same border/shadow aesthetic as the floating widget.

Backend connection: reads `window.__DD_CONFIG__.chatbot.backend_url` (set by root layout from `deepdoc.config.json`). Falls back to `http://127.0.0.1:{port}` via `chatbot_backend_base_url()` — user never needs to set it manually.

SSE field names (confirmed against backend):
- Request body: `{ question, history, max_rounds? }`
- Token events: `evt.text` (not `evt.content`)
- Event type header: `event: token` / `event: trace` / `event: result`

### 4. Chatbot response verbosity fix

`deepdoc/chatbot/answer_mixin.py` — replaced `## YOUR PRIMARY DIRECTIVE: BE EXHAUSTIVE` with a length-matching rule:
- Greetings / small-talk → 1-3 sentences, invite a real question
- Specific technical questions → thorough with code and evidence citations
- Broad questions → focused overview, not exhaustive dump

---

## Repos Updated

These repos had their `site/` shells regenerated and `site/app/ask/page.tsx` copied in sync:

| Repo | Path |
|------|------|
| backend-sync-api | `/Users/apple/tss/backend-sync-api/site/` |
| www.snitch.com | `/Users/apple/personal/www.snitch.com/site/` |
| youtube-notes | `/Users/apple/personal/youtube-notes/site/` |
| shotted | `/Users/apple/personal/shotted/site/` |

Any changes to `next_template/` need to be propagated to these repos manually (copy the changed files) until a proper `deepdoc generate --update-shell` command exists.

---

## How to Run

```bash
# Generate docs + site shell for a repo
cd ~/your-repo
deepdoc generate

# Serve locally (starts both backend and Next.js dev server)
deepdoc serve

# Production build
deepdoc deploy      # runs next build → site/out/
```

Node ≥ 18 required. `deepdoc serve` checks and errors clearly if missing. On first run it does `npm install` in `site/` automatically.

---

## Known Issues / Pending Work

### Shell sync problem
When `next_template/` changes (bug fixes, UI improvements), existing repos don't get the update automatically — their `site/` was written at `deepdoc generate` time. Current workaround: manually copy changed files. A proper fix would be a `deepdoc generate --refresh-shell` command that re-copies the template without regenerating docs.

### `app/[[...slug]]/page.tsx` duplicate
There are two catch-all routes: `app/[[...slug]]/page.tsx` and `app/(main)/[[...slug]]/page.tsx`. The top-level one should be removed — it's a leftover from before the route group was introduced. Next.js resolves the `(main)` group correctly so it's not actively breaking anything, but it's dead code.

### No `deepdoc generate` end-to-end test
`tests/test_next_builder.py` covers the builder in isolation. There's no integration test that runs a full `deepdoc generate` + `next build` and checks the output HTML. The MkDocs equivalent never had one either.

### Web server (`web/server/`) not tested with Node 18+ restriction
`worker.js` now runs `npm ci + next build` instead of `mkdocs build`. The server setup scripts (`setup.sh`, `deploy.sh`) install Node/pnpm but haven't been tested end-to-end against the new build pipeline.

### Sidebar footer on mobile
`dd-gen-meta` (commit SHA + generation date in sidebar footer) is hidden on mobile via `@media (max-width: 768px) { display: none }`. Fine for now but worth revisiting.

---

## Key File Map

| File | Role |
|------|------|
| `deepdoc/site/builder/next_builder.py` | Main builder — call `build_next_from_plan()` |
| `deepdoc/site/builder/next_template/` | Template shell copied into each repo's `site/` |
| `deepdoc/site/builder/__init__.py` | Exports `build_next_from_plan` |
| `deepdoc/chatbot/answer_mixin.py:275` | `_system_prompt()` — chatbot response instructions |
| `deepdoc/chatbot/settings.py` | `chatbot_backend_base_url()` — URL auto-resolution |
| `deepdoc/prompts/system.py` | Doc generation prompt — uses `:::note` directive syntax |
| `deepdoc/changelog_writer.py` | Uses `:::details[…]` syntax (not `/// details |`) |
| `deepdoc/generator/post_processors.py` | No longer rewrites `/slug` → `slug.md` links |
| `deepdoc/cli.py` | `serve` / `deploy` — Next.js commands |
