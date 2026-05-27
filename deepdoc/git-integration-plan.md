# Plan: Git-Native Doc Generation for DeepDoc

## Goal

Generation reads committed code at a specific git ref — not the working tree. Dirty files are
architecturally excluded, not warned about. `deepdoc generate` always pins to a commit.
`deepdoc update` stays working-tree based (it already diffs git commits). Commit badge in rendered
docs is a clickable link. `install-hooks` auto-runs `deepdoc update` after every commit/merge.

---

## Architecture: `GitContext` + `read_file()` helper

The codebase has ~30 scattered `path.read_text()` / `.exists()` calls with no central abstraction.
The correct fix is a thin `GitContext` dataclass + a `read_file()` helper injected through the
pipeline — **not** a wrapper class over every call site.

### New file: `deepdoc/git_reader.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import git


@dataclass
class GitContext:
    repo: git.Repo
    ref: str   # symbolic ("HEAD", "main", "v1.2.0") or sha
    sha: str   # resolved full 40-char sha

    def read(self, abs_path: Path) -> str:
        rel = Path(abs_path).relative_to(self.repo.working_dir)
        return self.repo.git.show(f"{self.ref}:{rel.as_posix()}")

    def exists(self, abs_path: Path) -> bool:
        rel = Path(abs_path).relative_to(self.repo.working_dir)
        try:
            self.repo.git.cat_file("-e", f"{self.ref}:{rel.as_posix()}")
            return True
        except git.GitCommandError:
            return False

    def list_tracked_files(self) -> list[Path]:
        """All files tracked at this ref (respects .gitignore automatically)."""
        output = self.repo.git.ls_tree("--name-only", "-r", self.ref)
        root = Path(self.repo.working_dir)
        return [root / f for f in output.splitlines() if f.strip()]

    @classmethod
    def resolve(cls, repo_root: Path, ref: str = "HEAD") -> GitContext:
        repo = git.Repo(repo_root, search_parent_directories=False)
        sha = repo.git.rev_parse(ref)
        return cls(repo=repo, ref=ref, sha=sha)


def read_file(path: Path, git_ctx: GitContext | None) -> str:
    """Read file content — from git object if git_ctx set, else filesystem."""
    if git_ctx is not None:
        return git_ctx.read(path)
    return path.read_text(encoding="utf-8", errors="replace")


def file_exists(path: Path, git_ctx: GitContext | None) -> bool:
    if git_ctx is not None:
        return git_ctx.exists(path)
    return path.exists()
```

`GitContext.resolve()` is the only public constructor. Everything else in the codebase uses the
injected instance.

---

## Change 1 — `parse_file()` gains `git_ctx` param

**File:** `deepdoc/parser/registry.py`

`parse_file` is called from 6+ places and is the key hub for source reads during scan and evidence
assembly. Adding `git_ctx` here propagates through all callers for free.

```python
# before (~line 33):
def parse_file(path: Path) -> ParsedFile | None:
    ext = path.suffix.lower()
    if ext not in _REGISTRY:
        return None
    language, parser_fn = _REGISTRY[ext]
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return parser_fn(path, content, language)
    except Exception:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""
        return ParsedFile(path=path, language=language, raw_content=content[:12000])

# after:
def parse_file(path: Path, git_ctx: GitContext | None = None) -> ParsedFile | None:
    from ..git_reader import read_file   # lazy import — avoids circular at module level
    ext = path.suffix.lower()
    if ext not in _REGISTRY:
        return None
    language, parser_fn = _REGISTRY[ext]
    try:
        content = read_file(path, git_ctx)
        return parser_fn(path, content, language)
    except Exception:
        try:
            content = read_file(path, git_ctx)
        except Exception:
            content = ""
        return ParsedFile(path=path, language=language, raw_content=content[:12000])
```

All 6 call sites of `parse_file(path)` continue to work unchanged (default `git_ctx=None`).
When the pipeline has a `GitContext`, it passes it explicitly.

---

## Change 2 — `scan_repo()` uses `GitContext` for discovery + reads

**File:** `deepdoc/planner/engine.py`

`scan_repo()` currently uses `rglob` / `os.walk` for file discovery and direct `fpath.read_text()`
for content. With `GitContext`, discovery switches to `git ls-tree` (which automatically
honors `.gitignore`) and reads go through `git_ctx.read()`.

**Signature change** (~line where `scan_repo` is defined):
```python
# before:
def scan_repo(repo_root: Path, cfg: Config) -> RepoScan:

# after:
def scan_repo(repo_root: Path, cfg: Config, git_ctx: GitContext | None = None) -> RepoScan:
```

**File discovery** (replaces the `rglob`/`os.walk` loop):
```python
# before: iterates rglob("**/*") or os.walk
# after — at the top of the walk loop, choose source:
if git_ctx is not None:
    all_files = git_ctx.list_tracked_files()
else:
    all_files = sorted(repo_root.rglob("*"))

for fpath in all_files:
    if not fpath.is_file():   # still needed for filesystem mode
        continue
    ...
```

**Direct `read_text` calls** in engine.py at ~lines 428, 463:
```python
# before:
doc_content = fpath.read_text(encoding="utf-8", errors="replace")
# and:
content = fpath.read_text(encoding="utf-8", errors="replace")

# after (import read_file, file_exists at top):
from ..git_reader import read_file, file_exists

doc_content = read_file(fpath, git_ctx)
content = read_file(fpath, git_ctx)
```

**`parse_file` calls** in engine.py (pass `git_ctx` through):
```python
# every call of the form:
parsed = parse_file(fpath)
# becomes:
parsed = parse_file(fpath, git_ctx)
```

---

## Change 3 — `EvidenceAssembler` carries `git_ctx`

**File:** `deepdoc/generator/evidence.py`

`EvidenceAssembler.__init__` already takes `repo_root` and `scan`. Add `git_ctx`:

```python
# before (~wherever __init__ is):
def __init__(self, repo_root: Path, scan: RepoScan, cfg: Config):
    self.repo_root = repo_root
    self.scan = scan
    self.cfg = cfg

# after:
def __init__(self, repo_root: Path, scan: RepoScan, cfg: Config,
             git_ctx: GitContext | None = None):
    self.repo_root = repo_root
    self.scan = scan
    self.cfg = cfg
    self.git_ctx = git_ctx
```

Replace all 6 direct `src_path.read_text(...)` / `ar_path.read_text(...)` calls inside the class
(~lines 247, 622, 796, 1328, 1512, 1567) with:
```python
from ..git_reader import read_file, file_exists

# before:
if not src_path.exists():
    continue
content = src_path.read_text(encoding="utf-8", errors="replace")

# after:
if not file_exists(src_path, self.git_ctx):
    continue
content = read_file(src_path, self.git_ctx)
```

---

## Change 4 — `PipelineV2` carries and propagates `git_ctx`

**File:** `deepdoc/pipeline_v2.py`

`PipelineV2.__init__` already takes `repo_root` and `cfg`. Add `git_ctx`:

```python
# before:
def __init__(self, repo_root: Path, cfg: Config):
    self.repo_root = repo_root
    self.cfg = cfg

# after:
def __init__(self, repo_root: Path, cfg: Config, git_ctx: GitContext | None = None):
    self.repo_root = repo_root
    self.cfg = cfg
    self.git_ctx = git_ctx
```

Propagate `git_ctx` at the two construction sites inside the pipeline:

1. Where `scan_repo(...)` is called (~line 862, 1019, 1440):
   ```python
   # before:
   scan = scan_repo(self.repo_root, self.cfg)
   # after:
   scan = scan_repo(self.repo_root, self.cfg, self.git_ctx)
   ```

2. Where `EvidenceAssembler(...)` is constructed:
   ```python
   # before:
   assembler = EvidenceAssembler(self.repo_root, scan, self.cfg)
   # after:
   assembler = EvidenceAssembler(self.repo_root, scan, self.cfg, self.git_ctx)
   ```

3. Direct `read_text` calls remaining in pipeline_v2.py (~lines 830–860, source context builder):
   ```python
   from .git_reader import read_file, file_exists
   # before:
   if not src_path.exists():
       continue
   content = src_path.read_text(encoding="utf-8", errors="replace")
   # after:
   if not file_exists(src_path, self.git_ctx):
       continue
   content = read_file(src_path, self.git_ctx)
   ```

---

## Change 5 — `deepdoc/updater_v2.py` direct reads

**File:** `deepdoc/updater_v2.py`

`update` is working-tree based by design — it diffs git commits. These reads stay on the
filesystem. **No change needed here.** `updater_v2.py` constructs `PipelineV2` for nav rebuild
only; that path doesn't re-scan sources.

The two `read_text` calls in updater_v2 (~lines 160, 179) are reading *unchanged* context files —
these should remain filesystem reads. Leave them as-is.

---

## Change 6 — `cli.py`: `--ref` on `generate`, store sha, install-hooks

**File:** `deepdoc/cli.py`

### 6a — `generate` command gets `--ref`

```python
@main.command()
@click.option("--ref", default="HEAD", show_default=True,
    help="Git ref (branch, tag, sha) to generate docs from. "
         "Defaults to HEAD (latest commit).")
# ... other existing options ...
def generate(ref, ...):
    repo_root = _find_repo_root()

    # Resolve git context — reads committed state, not working tree
    try:
        import git as _git
        from .git_reader import GitContext
        git_ctx = GitContext.resolve(repo_root, ref)
        sha_short = git_ctx.sha[:10]
        console.print(f"[dim]Generating docs from {ref} ({sha_short}...)[/dim]")
    except Exception:
        git_ctx = None   # fallback: filesystem (non-git repo)

    pipeline = PipelineV2(repo_root, cfg, git_ctx=git_ctx)
    ...
```

No dirty-tree warning needed — dirty files are physically excluded because we read git objects.

### 6b — Store `generated_from_sha` in deepdoc state

After pipeline completes, write the SHA to `.deepdoc/state.json` (or alongside plan) so
the commit badge and freshness detection can use it:

```python
# In cli.py after pipeline.run() completes:
if git_ctx:
    _write_generated_sha(repo_root, git_ctx.sha)
```

Add `_write_generated_sha` / `_read_generated_sha` private helpers that read/write a single key
in `.deepdoc/state.json` (the persistence module already owns this file).

Better: add `generated_from_sha: str` field to whatever state dataclass `persistence_v2.py`
already defines, and let pipeline set it.

### 6c — `install-hooks` command (unchanged from previous plan)

Add after the `clean` command block (~line 476):

```python
@main.command("install-hooks", short_help="Install git hooks to auto-run deepdoc update.")
@click.option("--append", is_flag=True,
    help="Append to an existing hook instead of skipping it.")
def install_hooks(append):
    """Install post-commit and post-merge git hooks to auto-update docs."""
    repo_root = _find_repo_root()
    hooks_dir = repo_root / ".git" / "hooks"
    if not hooks_dir.exists():
        raise click.ClickException("No .git/hooks directory found.")

    block = (
        '\n# Added by deepdoc install-hooks\n'
        'cd "$(git rev-parse --show-toplevel)"\n'
        'deepdoc update || true\n'
    )
    full_script = "#!/bin/sh\n" + block

    installed, skipped = [], []
    for hook_name in ("post-commit", "post-merge"):
        path = hooks_dir / hook_name
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if "deepdoc update" in existing:
                skipped.append(f"{hook_name} (already contains deepdoc)")
                continue
            if append:
                path.write_text(existing.rstrip("\n") + block, encoding="utf-8")
                installed.append(f"{hook_name} (appended)")
            else:
                skipped.append(f"{hook_name} (exists — use --append to add deepdoc)")
        else:
            path.write_text(full_script, encoding="utf-8")
            path.chmod(0o755)
            installed.append(hook_name)

    if installed:
        console.print(f"[green]✓ Installed:[/green] {', '.join(installed)}")
    if skipped:
        console.print(f"[dim]Skipped: {', '.join(skipped)}[/dim]")
```

---

## Change 7 — Clickable commit badge in rendered docs

**Files:** `deepdoc/site/builder/scaffold_files.py`, `deepdoc/site/builder/engine.py`

### `scaffold_files.py`

Change `_docs_page_tsx` signature:
```python
def _docs_page_tsx(repo_url: str = "") -> str:
```

Replace the `lastIndexedLabel` / commitId render block with:
```typescript
// baked-in at scaffold time by Python:
const repoUrl = '{repo_url}';

{(lastIndexed || commitId) ? (
  <p style={{ marginTop: 0, marginBottom: '1rem', fontSize: '0.875rem',
              color: 'var(--color-fd-muted-foreground)' }}>
    {lastIndexed ? `Last indexed: ${lastIndexed}` : 'Last indexed'}
    {commitId ? (
      <>
        {' ('}
        {repoUrl
          ? <a href={`${repoUrl}/commit/${commitId}`}
               style={{ color: 'inherit', textDecoration: 'underline' }}>
              {commitId}
            </a>
          : commitId
        }
        {')'}
      </>
    ) : null}
  </p>
) : null}
```

Works for GitHub, GitLab, Gitea, Bitbucket — all use `/commit/<sha>`.

### `engine.py`

`repo_url` is already in scope in `_ensure_app_scaffold()` (third param, used for `_layout_options_ts`).
One-line change at ~line 72:
```python
# before:
site_dir / "app" / "[[...slug]]" / "page.tsx": _docs_page_tsx(),
# after:
site_dir / "app" / "[[...slug]]" / "page.tsx": _docs_page_tsx(repo_url),
```

---

## Files Modified (complete list)

| File | Change |
|------|--------|
| `deepdoc/git_reader.py` | **NEW** — `GitContext`, `read_file()`, `file_exists()` |
| `deepdoc/parser/registry.py` | `parse_file(path, git_ctx=None)` |
| `deepdoc/planner/engine.py` | `scan_repo(..., git_ctx=None)`; file discovery via `git ls-tree`; reads via `read_file()` |
| `deepdoc/generator/evidence.py` | `EvidenceAssembler.__init__` gains `git_ctx`; 6 reads → `read_file()` |
| `deepdoc/pipeline_v2.py` | `PipelineV2.__init__` gains `git_ctx`; propagates to `scan_repo` + `EvidenceAssembler`; direct reads → `read_file()` |
| `deepdoc/cli.py` | `generate` gains `--ref`; resolves `GitContext`; writes `generated_from_sha`; adds `install-hooks` |
| `deepdoc/site/builder/scaffold_files.py` | `_docs_page_tsx(repo_url="")` — clickable commit link |
| `deepdoc/site/builder/engine.py` | Pass `repo_url` to `_docs_page_tsx()` |

`deepdoc/updater_v2.py` — **no change** (update is intentionally working-tree based).

---

## Backward compatibility

- All new params default to `None` / `""` — no call sites break.
- Non-git repos: `GitContext.resolve()` raises, `cli.py` catches it and falls back to `git_ctx=None`
  (filesystem reads, current behavior).
- `generate --ref HEAD` (default) is identical to old behavior for committed code; only difference
  is dirty working-tree files are now silently excluded rather than silently included.

---

## Tests to add / update

| Test file | What to cover |
|-----------|--------------|
| `tests/test_git_reader.py` | **NEW** — `GitContext.read()`, `exists()`, `list_tracked_files()`; `read_file()` fallback; `resolve()` on a non-git dir raises |
| `tests/test_cli_update.py` | Stage a file without committing, run `deepdoc generate`, assert the staged content is NOT in generated docs (verifies git-native read) |
| `tests/test_fumadocs_builder.py` | `_docs_page_tsx(repo_url="https://github.com/a/b")` → contains `/commit/`; `_docs_page_tsx("")` → no `<a href` |
| `tests/test_cli_update.py` (new case) | `install-hooks` writes correct files; `--append` appends; idempotent on second run |

---

## Verification

```bash
python -m compileall deepdoc

# unit + integration
python -m pytest tests/test_git_reader.py tests/test_cli_update.py tests/test_fumadocs_builder.py -q

# manual: git-native generate
git stash                           # or leave working tree dirty — shouldn't matter
deepdoc generate                    # reads HEAD, prints "Generating docs from HEAD (abc1234567...)"
deepdoc generate --ref main         # same
deepdoc generate --ref v1.0.0       # tag

# manual: hooks
deepdoc install-hooks               # writes post-commit + post-merge
deepdoc install-hooks               # "already contains deepdoc"
deepdoc install-hooks --append      # appends

# manual: commit badge
# check site/app/[[...slug]]/page.tsx for href="/commit/"
```
