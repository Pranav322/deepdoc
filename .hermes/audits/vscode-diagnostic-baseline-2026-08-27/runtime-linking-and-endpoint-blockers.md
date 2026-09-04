# DD-001/DD-002 Final-Review Blockers

**Reviewed head:** `4c6708fcd6bc6222eac78bdd967bd0ca2882c9df` on `fix/runtime-scan-stabilization`.

The JS queue API-role follow-up is accepted as a scoped semantic improvement, but the broader runtime branch is not mergeable yet.

## Independently reproduced blockers

### DD-001 — marker candidate scan remains task-count proportional
`_link_runtime_workflows()` first selects files with `DISPATCH_MARKER_RE`, then loops every runtime task for every selected file. A deterministic direct replay with 251 runtime tasks and 257 unrelated files containing `.delay(` measured **64,507** token membership checks (`251 × 257`), where a bounded target-extraction design should have no task lookup for these nonmatching calls.

This can recur in any repository with many generic dispatch-shaped calls. It is not VS Code-specific.

### DD-002 — unpublished endpoint evidence leaks into runtime facts
A product Celery dispatch in `app/api.py` plus an endpoint record owned by that file with `publication_ready=False` produced:

```text
RuntimeTask.linked_endpoints = ['GET /test-only']
```

The engine passes raw `scan.api_endpoints`, while `RepoScan.published_api_endpoints` already defines the canonical trust boundary. Runtime discovery must also defend its public/direct-call boundary.

## Required correction

A fresh Claude Opus TDD follow-up is authorized by the existing DD-001/DD-002 scope. It must use indexed dispatch-target extraction instead of candidate-file × all-task scanning, and must reject unpublished endpoint records at both appropriate seams. No merge/PR/production-checkout modification is authorized.