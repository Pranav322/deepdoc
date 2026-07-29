# HANDOFF — Hosted DeepDoc ("Try DeepDoc") product

Session handoff for the **hosted generation product** built this session (a
no-CLI web flow: sign in with GitHub → pick/paste a repo → get a generated docs
site). This is separate from the `deepdoc` Python package and from the older
`deepdoc/HANDOFF.md` (which is about the core pipeline). Deeper reference:
**`docs/PRODUCTION_INFRA.md`** (full resource inventory + runbook + teardown).

## ⚠️ Update 2026-07-28: this section is now stale — everything below is committed
All the work originally described as "uncommitted" has since been committed and deployed
across many follow-up sessions (video R2 hosting, sign-in modal redesign, public docs
gallery, Bun migration, several production bugfixes — see commits `615b82a`..`9b02dd6` on
`main`, chronological, newest last). `docs/PRODUCTION_INFRA.md` and `docs/HOSTED_UI_SPEC.md`
were later **deleted from the working tree by an external process** (not by any agent) —
user said explicitly **"for now let them stay deleted"**; do not restore them without being
asked again. Untracked `.deepdoc/`, `.deepdoc_file_map.json`, `.deepdoc_plan.json`,
`chatbot_backend/` also appeared from that same process and have been left alone in every
commit since.
Commit rule (user's): **no Claude/AI attribution or co-author lines** — author is the user only.

## Current live state (all verified green)
Everything is deployed and working in production:
- **Marketing site** → `deepdoc.tech` (Cloudflare **Pages** project `deepdoc`, NOT Vercel — old docs were wrong). Deploy: `cd web && pnpm build && npx wrangler pages deploy dist --project-name=deepdoc`.
- **Hosted app** → `cloud.deepdoc.tech` (Cloudflare Worker `deepdoc-hosted`). Deploy: `cd web/hosted && npx wrangler deploy`.
- **Generation compute** → event-driven Azure Container Apps **Job** `deepdoc-gen-job` (autoscaling, scale-to-zero). The old always-on `deepdoc-runner` Container App is **deleted**. Runner image now `deepdoc-runner:v7` (was v5 — see "2026-07-28 production incidents" below). `replicaTimeout` raised from 3600s to **86400s** (24h) — a large repo generation must never be killed by an arbitrary timeout; let it finish or throw a real error.

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
- LLM: Azure AI Foundry `deepdoc-foundry` / `DeepSeek-V4-Flash` — real deployment limits are **1,000,000 token context window / 128,000 token max output**. `hosted-runner/pipeline.py`'s `DEEPDOC_YAML` template previously hardcoded `context_window_tokens: 128000` / `output_reserve_tokens: 16000` — that 128000 was actually the *output* limit mistaken for the context window, making the planner's real budget ~8x smaller than the model's true capacity. Fixed 2026-07-28 to `context_window_tokens: 1000000` / `output_reserve_tokens: 128000` (commit `9b02dd6`). Needs `AZURE_API_KEY` (not `AZURE_OPENAI_API_KEY`).

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

## Features shipped since this doc was written (2026-07-24 → 2026-07-28)
- **Demo video hosted on R2**, autoplay-muted on viewport entry / pause on exit (`615b82a`).
- **GitHub sign-in modal redesign** on both `deepdoc.tech` and `cloud.deepdoc.tech` (`80d93f9`).
- **Public docs gallery** on `cloud.deepdoc.tech` root for unauthenticated visitors: card grid of
  already-public generated sites (live iframe preview of each site's real homepage, CSS-only 3D
  tilt-on-hover, conic-gradient "border beam" hover effect — no third-party libs), "Generate your
  own" only opens the sign-in modal on click, marketing site's "Try the Demo" now navigates
  straight to `cloud.deepdoc.tech` instead of opening its own modal (`b5a25b8`, `fe3a472`,
  `64fd86f`, `125646b`). New endpoint `web/src/pages/cloud/api/examples.ts` (unauthenticated GET,
  joins `owner_repo_jobs` + `projects`, filters `visibility='public' AND status='done'`).
- **Package manager**: `web/` migrated pnpm → Bun (`1f74519`; `bun.lock`, not `pnpm-lock.yaml`).

## 2026-07-28 production incidents (all root-caused and fixed)
- **Recursive-gallery bug**: visiting `cloud.deepdoc.tech/{owner}/{repo}/` directly while
  unauthenticated showed the full public gallery instead of that repo's actual state — `main()`
  in `page_html.ts` called `renderLoggedOut()` unconditionally for any unauthenticated visitor,
  ignoring the URL. Fixed with a pathname check + new `renderPublicInProgress()` (`40ed0a3`).
- **Race-condition "stale/regenerate" screen**: a job with `status: null` in R2 (real gap right
  after enqueue, before the runner writes its first status) was shown the "site unavailable,
  regenerate" error instead of a progress view — `web/src/pages/cloud/[owner]/[repo]/[...path].ts`
  treated `result.status && ...` as falsy for `null`. Fixed to explicit
  `status !== "done" && status !== "failed"` (`5f18160`).
- **`karpathy/nanochat` generation failure — UNRESOLVED, needs resuming**: root-caused via direct
  D1/R2 inspection to `validate_plan_contract()` rejecting a duplicate LLM-assigned bucket title
  ("Common Utilities & Configuration" assigned to two different clusters by the classify step) →
  slug collision. User said "yes" to fixing it; an Explore agent was launched to trace the
  classify/naming/slugify code in `deepdoc/planner/*` but was interrupted before returning
  results and **has never been resumed**. Next session: relaunch that trace (likely fix is either
  de-duping cluster names post-LLM-classify, or appending a disambiguating suffix before slugify).
- **`microsoft/vscode` generation "hanging" for ~12 hours — two real root causes found**:
  1. `deepdoc-gen-job`'s Container Apps Job `replicaTimeout` was hardcoded to 3600s (1h), silently
     SIGTERM-killing large-repo generations mid-scan. User: "why are we putting timeout... just
     let it generate until it finishes or throw error." Raised to 86400s via
     `az containerapp job update -n deepdoc-gen-job -g deepdoc-main --replica-timeout 86400`.
  2. The wrong hardcoded `context_window_tokens: 128000` (see LLM section above) meant the
     classify step's real budget was ~8x too small; a 154,168-token required classify prompt for
     vscode hard-failed `ModelCapabilityError` after already burning ~10+ hours in scan. Fixed to
     the real 1M/128K limits.
  3. **Observability gap found mid-investigation**: `hosted-runner/pipeline.py`'s `_run()` used
     `subprocess.run(capture_output=True)`, which fully buffers the child process's stdout/stderr
     until it exits — so Azure's log stream showed *nothing* for hours regardless of whether the
     job was working or hung, making "is it stuck?" impossible to answer from logs alone. User
     explicitly required real-time visibility ("make sure this time we have proper logs that
     deepdoc outputs in our azure logs too"). Fixed by switching to `subprocess.Popen` + line-by-
     line `print(..., flush=True)` streaming. Rebuilt as `deepdoc-runner:v7`, redeployed the Job.
     **Verified working in production**: the very next real job (`openclaw/openclaw`,
     `1898bf68bbaa`) showed genuine live per-file clustering output in
     `az containerapp job logs show` for the first time in this entire investigation.
  - Side note (documented, not yet explained anywhere else): a Container Apps Job **execution**
    can show `Succeeded` at the process-exit level even when the *application* logically failed —
    `run_generation()` in `pipeline.py` catches exceptions internally and returns
    `{"status": "failed", ...}` (writes it to R2 status.json) but still exits the Python process
    cleanly (code 0). Ground truth for "did the generation actually work" is always R2
    `status.json`, never the Azure execution status alone.
- **Useful ops commands learned this round**: `az containerapp job logs show -n deepdoc-gen-job
  -g deepdoc-main --container deepdoc-gen-job --execution <exec-name> --tail 60 [--follow]`
  (the `--container` flag is required, easy to forget). `az containerapp job execution list -n ...
  -g ... -o table` (avoid a custom `--query "sort_by(...)"` — a null `startTime` field across
  entries throws a JMESPath type error; plain `-o table` is fine). Azure Monitor CPU
  (`UsageNanoCores`) metric is a decent "is it actually working" proxy when logs are silent.
  GUI equivalent: Azure Portal → the `deepdoc-gen-job` Container App Job resource → **Log
  stream** / **Execution history** / **Logs** blades.

## Discussed but NOT implemented (no decision yet)
- Multi-API-key / multi-model failover + concurrency-aware load balancing (adding Kimi-K2.6 and
  DeepSeek-V4-Pro as additional keys/models, routing around failures, using all keys at once when
  only one generation is running vs. one-key-per-job when several run concurrently) — discussed
  at a "think first" analysis level only per user's request. Recommendation given: build failover
  first (cheap, immediately useful), concurrency-aware pooling later, check telemetry before
  investing further. User has not yet responded to that recommendation.

## Suggested next steps
1. Resume the `karpathy/nanochat` duplicate-bucket-slug planner bug fix (see above) — this is the
   one concretely-agreed-to task still not done.
2. Decide on the multi-API-key/failover proposal above, if still wanted.
3. Optionally tighten the KEDA no-op (lower `--replica-timeout` back down once large-repo timeouts
   are no longer a concern, or add a drain-loop in job.py).
4. Regenerate the architecture/DevOps artifacts to reflect the queue+Jobs model (still pending
   from the original handoff).
5. If concurrency grows: consider a token-broker so the GitHub token doesn't transit the queue.
