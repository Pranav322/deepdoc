# Plan: Git-Native Integration for DeepDoc

## Context

DeepDoc currently generates docs from the working tree without awareness of git commit state. The user wants:
- Docs to warn when uncommitted changes exist (those changes won't be reflected)
- `deepdoc install-hooks` to auto-run `deepdoc update` after every commit/merge
- Each rendered doc page to show which commit it was generated from, as a **clickable link**

Three targeted changes. No breaking refactors.

---

## Change 1 — Uncommitted-changes warning (`generate` + `update`)

**Problem:** Running `deepdoc generate` with staged/unstaged files silently scans dirty code. Docs end up reflecting uncommitted state with no indication to the user.

**Files:** `deepdoc/cli.py` only.

**How:** Add a private helper near the other `_find_*` helpers at the bottom of `cli.py`:

```python
def _warn_if_dirty(repo_root: Path) -> None:
    try:
        import git
        repo = git.Repo(repo_root, search_parent_directories=False)
        if repo.is_dirty(untracked_files=False):
            short = repo.head.commit.hexsha[:10]
            console.print(
                "[yellow]⚠ Working tree has uncommitted changes — they will NOT be "
                "reflected in generated docs.[/yellow]\n"
                f"[dim]  Docs are generated from committed code (HEAD: {short}...).\n"
                "  Commit or stash your changes first for accurate results.[/dim]"
            )
    except Exception:
        pass  # not a git repo or git unavailable — silently skip
```

Call `_warn_if_dirty(repo_root)` in:
- `generate()` — right after `repo_root = _find_repo_root()` (~line 381)
- `update()` — right after `repo_root = _find_repo_root()` (~line 516)

GitPython (`import git`) is already a project dependency, used in `smart_update_v2.py` and `pipeline_v2.py`.

---

## Change 2 — `deepdoc install-hooks` command

**Problem:** No mechanism auto-runs `deepdoc update` after commits. Engineers must remember manually.

**Files:** `deepdoc/cli.py` only — new `@main.command`.

**How:** Add after the `clean` command block (~line 476):

```python
@main.command("install-hooks", short_help="Install git hooks to auto-run deepdoc update.")
@click.option("--append", is_flag=True,
    help="Append to an existing hook instead of skipping it.")
def install_hooks(append):
    """Install post-commit and post-merge git hooks to auto-update docs.

    After installation, `deepdoc update` runs automatically on every commit
    and merge. If a hook file already exists, use --append to add deepdoc to
    it rather than leaving it untouched.
    """
    repo_root = _find_repo_root()
    hooks_dir = repo_root / ".git" / "hooks"
    if not hooks_dir.exists():
        raise click.ClickException("No .git/hooks directory found. Is this a git repository?")

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

Hook output is **visible** by default (`|| true` prevents the hook from blocking commits on deepdoc failure).

---

## Change 3 — Clickable commit badge in rendered docs

**Problem:** "Last indexed: date (sha)" is plain text. Engineers can't click to the commit.

**Files:**
- `deepdoc/site/builder/scaffold_files.py` — `_docs_page_tsx()` signature + TSX template
- `deepdoc/site/builder/engine.py` — pass `repo_url` at the call site (~line 72)

**How:**

**`scaffold_files.py`** — change signature:
```python
def _docs_page_tsx(repo_url: str = "") -> str:
```

Inside the function, `repo_url` is a Python value baked into the template string at scaffold-generation time (same pattern as `_layout_options_ts`). Replace the plain `lastIndexedLabel` render block with:

```typescript
// baked-in value from Python at scaffold time:
const repoUrl = '{repo_url}';   // empty string when not configured

// replace the lastIndexedLabel logic with direct commit link rendering:
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

Works for **any `repo_url`** — GitHub, GitLab, Gitea, Bitbucket all use `/commit/<sha>`. No host-name filtering.

**`engine.py`** — one-line change at ~line 72:
```python
# before:
site_dir / "app" / "[[...slug]]" / "page.tsx": _docs_page_tsx(),
# after:
site_dir / "app" / "[[...slug]]" / "page.tsx": _docs_page_tsx(repo_url),
```

`repo_url` is already in scope in `_ensure_app_scaffold()` (it's the third parameter, already used for `_layout_options_ts`).

Also check `site/builder/engine.py` line 508 — it imports `_docs_page_tsx` from `.templates`. The re-export in `templates.py` doesn't need to change since it just re-exports the function by name.

---

## Files Modified (complete list)

| File | Change |
|------|--------|
| `deepdoc/cli.py` | Add `_warn_if_dirty()` helper; call it in `generate` + `update`; add `install-hooks` command |
| `deepdoc/site/builder/scaffold_files.py` | `_docs_page_tsx(repo_url="")` — new param + updated TSX block |
| `deepdoc/site/builder/engine.py` | Pass `repo_url` to `_docs_page_tsx()` at ~line 72 |

---

## Tests to add

- `tests/test_cli_update.py` — stage a change without committing in `tmp_repo_with_plan`, assert dirty warning is in output
- `tests/test_fumadocs_builder.py` — assert generated `page.tsx` contains `/commit/` link when `repo_url` is set; assert it does not when `repo_url` is empty

---

## Verification

```bash
python -m compileall deepdoc
python -m pytest tests/test_cli_update.py tests/test_fumadocs_builder.py -q

# Manual:
deepdoc install-hooks               # writes post-commit + post-merge
deepdoc install-hooks               # "already contains deepdoc"
deepdoc install-hooks --append      # appends to existing

# Stage a file (don't commit), then:
deepdoc generate                    # prints dirty-tree warning
deepdoc update                      # same

# Check site/app/[[...slug]]/page.tsx contains /commit/ link when repo_url set
```
