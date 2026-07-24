# HANDOFF — Hosted DeepDoc ("Try DeepDoc") product

Session handoff for the **hosted generation product** built this session (a
no-CLI web flow: sign in with GitHub → pick/paste a repo → get a generated docs
site). This is separate from the `deepdoc` Python package and from the older
`deepdoc/HANDOFF.md` (which is about the core pipeline). Deeper reference:
**`docs/PRODUCTION_INFRA.md`** (full resource inventory + runbook + teardown).

## ⚠️ FIRST: nothing is committed
All of this session's work is **uncommitted on `main`**:
- `?? hosted-runner/` (new), `?? web/hosted/` (new) — untracked
- `M AGENTS.md`, `M web/src/pages/index.astro`, `M deepdoc/site/builder/next_template/lib/docs.ts`, `M .gitignore`, `M CONTRIBUTING.md`
- `docs/PRODUCTION_INFRA.md` (new), this `HANDOFF.md` (new)
- `.env` and `web/hosted/.dev.vars` hold **real secrets** and are gitignored — verify they stay ignored before any `git add`.
Commit rule (user's): **no Claude/AI attribution or co-author lines** — author is the user only. Nothing has been pushed. Marketing/worker deploys were done via `wrangler`, not git.

## Current live state (all verified green)
Everything is deployed and working in production:
- **Marketing site** → `deepdoc.tech` (Cloudflare **Pages** project `deepdoc`, NOT Vercel — old docs were wrong). Deploy: `cd web && pnpm build && npx wrangler pages deploy dist --project-name=deepdoc`.
- **Hosted app** → `cloud.deepdoc.tech` (Cloudflare Worker `deepdoc-hosted`). Deploy: `cd web/hosted && npx wrangler deploy`.
- **Generation compute** → event-driven Azure Container Apps **Job** `deepdoc-gen-job` (autoscaling, scale-to-zero). The old always-on `deepdoc-runner` Container App is **deleted**.

## Architecture (Cloudflare edge + Azure compute)
```
Worker (cloud.deepdoc.tech)                      Azure (rg: deepdoc-main / eastus)
  GitHub OAuth, repo picker, /account,             Storage Queue deepdoc-jobs
  quotas, visibility, vanity /owner/repo/    ──▶    (acct deepdocjobs)
  handleGenerate = ENQUEUE base64(JSON)                 │ KEDA azure-queue scaler
                                                        ▼
  reads status + serves sites from R2  ◀──   Container Apps Job deepdoc-gen-job
                                               1 msg → 1 isolated execution
                                               4 vCPU / 8 GiB, min 0 / max 10
                                               clone → deepdoc generate → deploy
                                               → upload site + status.json → R2
                                               → delete msg → exit (scale to 0)
  D1 deepdoc-hosted-db: sessions, projects, quotas, oauth_states, owner_repo_jobs
  R2 deepdoc-hosted-sites: {owner}/{repo}/… (sites) + jobs/{id}/status.json
```

## Key files
- `web/hosted/src/index.ts` — the Worker (auth, dispatch=enqueue, status from R2, vanity serving, visibility enforcement, quotas). `web/hosted/src/try_page.ts` — server-rendered SPA (login / dashboard / `/account` / progress / private+stale pages). `web/hosted/schema.sql` + `web/hosted/migrations/`.
- `hosted-runner/pipeline.py` — shared clone→generate→deploy→R2 + `write_status`. `hosted-runner/job.py` — Job entrypoint (queue consumer). `hosted-runner/app.py` — legacy HTTP server, **vestigial** post-cutover. `hosted-runner/Dockerfile` (build context = repo root). Image: `deepdoc-runner:v5` in ACR `deepdocacr`.
- `deepdoc/site/builder/next_template/lib/docs.ts` — has `rehypeBasePath` (in-content link basePath fix).

## Secrets (three stores, no shared vault — deliberate)
- **Worker** (`wrangler secret`): `GITHUB_CLIENT_ID`, `GITHUB_SECRET_ID`, `QUEUE_MESSAGES_URL` (queue `/messages` endpoint + add-only SAS).
- **Job** (Container App Job secrets): `azure-api-key`, `r2-access-key-id`, `r2-secret-access-key`, `queue-conn`.
- **Local**: repo-root `.env` (AZURE_API_KEY, GITHUB_*, R2_*, RUNNER_SHARED_SECRET) + `web/hosted/.dev.vars`. Both gitignored.
- LLM: Azure AI Foundry `deepdoc-foundry` / `DeepSeek-V4-Flash` — needs explicit `context_window_tokens: 128000` + `output_reserve_tokens: 16000` in `.deepdoc.yaml`, and `AZURE_API_KEY` (not `AZURE_OPENAI_API_KEY`).

## Product rules implemented
- **Visibility**: sites default **private** (server-enforced in `handleOwnerRepoSite` — a private site needs `session.login == owner_login` before serving ANY byte incl. `/_next/*`; real boundary because R2 isn't public). Toggle via `POST /api/projects/:owner/:repo/visibility`.
- **One canonical site per repo**: first generator owns it (`owner_repo_jobs.owner_login`, set once); a 2nd user gets **409**.
- **Quotas**: 2 saved projects + 2 gen/24h per user; **`Pranav322` is unlimited** (`UNLIMITED_LOGINS` allowlist in index.ts).
- **Login persists 30 days** (cookie `Max-Age` matches session TTL).
- Message encoding contract: Worker `btoa(JSON)` ↔ job.py `TextBase64DecodePolicy` — keep in sync.

## Known limitations / gotchas (all documented, none blocking)
- **KEDA polling race** can spawn a duplicate **no-op** execution per message; harmless (only one leases the message → no duplicate generation), but a lingering `Running` one is billable → `az containerapp job stop -n deepdoc-gen-job -g deepdoc-main --job-execution-name <name>`.
- Single big-repo generation is ~25 min (LLM/token-rate bound, not infra) — autoscaling fixes concurrency/contention/idle-cost, not single-job latency. `max_parallel_workers: 6` inside a generation.
- GitHub token rides in the queue message (private queue, deleted after use) — token-broker is future work.
- Deploying a new Job image: `az acr build -r deepdocacr -t deepdoc-runner:vN ...` then `az containerapp job update -n deepdoc-gen-job --image ...:vN` (does NOT disrupt in-flight — new executions use the new image).
- No staging env, no CI/CD (all manual CLI deploys) — see the DevOps artifact.
- Orphaned AWS budget (`deepdoc-hosted-monthly`, $20/mo) from an abandoned AWS plan — no AWS resources exist, safe to delete.

## Cost guardrail
Azure budget `deepdoc-hosted-monthly` = ₹4,831/mo (≈$50, INR-billed — snapshot conversion, not pegged), alerts → pranavisverysad@gmail.com.

## Reference artifacts (claude.ai/code/artifact)
- Architecture: `d72d3046-06dc-4d7c-a9e9-8f0f7aa55f25`
- DevOps/ops: `914916e2-f412-42b5-9fec-3af52c27fd68`
(These predate the queue migration — the two-clouds framing still holds, but the runner is now the Job; regenerate if you want them exact.)

## Suggested next steps (not started)
1. **Commit this work** (author = user only, no AI attribution) — it's all uncommitted.
2. Optionally tighten the KEDA no-op (lower `--replica-timeout`, or drain-loop in job.py).
3. Regenerate the architecture/DevOps artifacts to reflect the queue+Jobs model.
4. If concurrency grows: consider a token-broker so the GitHub token doesn't transit the queue.
