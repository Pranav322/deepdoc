# Handoff — DD-001/DD-002 Linking and Endpoint Blockers

- **Branch/worktree:** `fix/runtime-scan-stabilization` at `4c6708f`, isolated and unmerged.
- **Universal scope:** DeepDoc runtime facts for any repository. VS Code remains only the large pinned stress corpus.
- **Accepted so far:** source-role/language gating, phase labels, JS/TS/Vue syntax binding, and queue API-role contracts.
- **Not accepted:** runtime linking still performs marker-file × task scanning; unpublished endpoints can be linked to product runtime tasks.

## Exact independent RED replay

```text
251 tasks × 257 unrelated `.delay(` files -> 64,507 token checks
publication_ready=False GET /test-only -> RuntimeTask.linked_endpoints=['GET /test-only']
```

## Next action

Claude Opus 5 must perform the bounded-target-index/publication-boundary correction using `.hermes/briefs/DD-001-DD-002-linking-endpoint-completion-claude-brief.md`, TDD first, no merge/push. Afterward independently inspect the diff and rerun focused/full/VS Code phase-only checks before asking Pranav for merge review.