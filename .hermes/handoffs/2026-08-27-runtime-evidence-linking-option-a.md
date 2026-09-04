# Runtime evidence linking — Option A handoff

## Status

**Verification pending; do not push, open a PR, merge, rebase, reset, or modify `main`.**

- Worktree: `/Users/apple/tss/codegen/codewiki-worktrees/runtime-evidence-linking`
- Branch: `fix/runtime-evidence-linking`
- Candidate head: `cc87fcc41240da61cd7a03d8e55e6405b0fbacec` (`fix: harden runtime evidence boundaries`)
- Base: `8d45e5a82487d37a2a4adbf622ffbff1a0cc4b22`
- Worktree was clean after the commit.

## What the candidate repairs

Fresh exact-head review findings from `415ab68` were addressed with RED→GREEN regressions:

1. Queue producer links use literal queue identity only; no terminal/suffix alias fallback.
2. Python dispatch evidence requires discovered local/import task bindings and explicit Django signal bindings; lexical scope and module source-order writes are respected.
3. Vue comments and template-nested script-like markup cannot produce executable SFC runtime evidence.
4. Renamed node-cron `schedule` exports reach the bound-call resolver.
5. PHP class aliases are namespace-scoped and case-insensitive; function import/local `dispatch`/`event` shadows reject false Laravel evidence.
6. Existing bounded direct/queue/scheduler behavior and JS binder contracts remain covered.

## Local verification already performed

- Full suite: `683 passed, 3 skipped` using `/Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -p no:cacheprovider -q`
- Runtime module: `82 passed`
- Smart-update/fingerprint module: `32 passed`
- Named repaired-boundary slice: `10 passed`
- `compileall` and `py_compile` on changed modules passed.
- `git diff --check` passed; added-line security scan found no secrets, shell execution, eval/exec, unsafe deserialization, or merge markers.
- Ruff is now installed. It reports exactly two verified pre-existing findings in `deepdoc/scanner/runtime.py`: F403 at line 6 (`from .common import *`) and E402 at the pre-existing late `from .utils import endpoint_owned_files`; neither was changed by this repair.

## Independent acceptance gate

Fresh read-only exact-head review batch is running:

- Delegation: `deleg_ebc45254`
- Required head: `cc87fcc41240da61cd7a03d8e55e6405b0fbacec`
- Reviews: complete release, parser/binder boundaries, boundedness/scheduler ownership, adversarial acceptance matrix.

Only complete, exact-head PASS verdicts may clear this candidate. Any blocker requires a new RED→GREEN repair commit and a new review batch pinned to the replacement head.

## Continuity / constraints

- Keep `.hermes/` artifacts uncommitted.
- The VS Code corpus is stress-only; no corpus-specific heuristics.
- Canonical end-to-end VS Code benchmark certification is still unavailable because of provider rate limiting; local tests do not replace it.
- Pranav must explicitly approve any future PR/merge after acceptance.

## Safe next action

Wait for `deleg_ebc45254`; assess every complete JSON verdict fail-closed. If all pass, update the issue ledger to `verification` with this evidence and report the candidate as locally accepted but awaiting explicit merge approval. If any fail, reproduce its exact issue before editing.
