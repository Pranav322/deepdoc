# Production infrastructure — hosted-generation ("Try DeepDoc")

This is the maintenance reference for the real Azure + Cloudflare infrastructure
behind the hosted "generate docs from a GitHub repo, no CLI" flow at
**cloud.deepdoc.tech**. See `AGENTS.md`'s "Hosted-generation" section for the
local dev setup this deploys from (`web/` + `hosted-runner/`).

**2026-07-25 — Cloudflare side unified.** `web/hosted/` (a standalone
Cloudflare Worker) is retired. The hosted app now lives inside the same
Astro project as the marketing site (`web/`), deployed as one Cloudflare
**Pages** project (`deepdoc`) with two custom domains: `deepdoc.tech`
(marketing, static) and `cloud.deepdoc.tech` (the hosted app, SSR via
`@astrojs/cloudflare`). The Azure side (`hosted-runner/`, the queue, the
Container Apps Job, Foundry) is completely unaffected — it only ever talked
to Cloudflare D1/R2, never to the Worker/Pages layer directly, so none of
that changed. See `AGENTS.md`'s "Hosted-generation" section for exactly what
moved and why.

## Resource inventory

| Resource | Location | Purpose | Secret / credential location |
|---|---|---|---|
| `deepdocacr` (Azure Container Registry, Basic) | `deepdoc-main`/`eastus` | Stores the runner image (`deepdoc-runner:v5` = the queue-consumer) | ACR admin credentials — `az acr credential show -n deepdocacr` |
| `deepdoc-runner-env` (Container Apps environment) | `deepdoc-main`/`eastus` | Hosting environment for the Job | n/a |
| **`deepdoc-gen-job`** (Container Apps **Job**, event-triggered) | `deepdoc-main`/`eastus` | **The generation compute.** KEDA `azure-queue` scaler on `deepdoc-jobs`; **min 0 / max 10**, **4 vCPU / 8 GiB** per execution, `--command python --args job.py`. One queue message → one isolated execution → clone/generate/deploy → upload site + `status.json` to R2 → delete message → exit. **Scale-to-zero when idle (~$0).** | `azure-api-key`, `r2-access-key-id`, `r2-secret-access-key`, `queue-conn` — Container App Job secrets |
| **`deepdocjobs`** (Storage account) + queue **`deepdoc-jobs`** | `deepdoc-main`/`eastus` | The dispatch queue the Cloudflare side enqueues to and the Job consumes | account key in the storage-account conn string; queue-scoped add-only SAS given to Cloudflare |
| `workspace-deepdocmainsNTF` (Log Analytics, auto-created) | `deepdoc-main`/`eastus` | Job execution logs | n/a |
| `deepdoc-foundry` (existing, pre-dates this deployment) | `deepdoc-main`/`eastus` | Azure AI Foundry account serving `DeepSeek-V4-Flash` | Foundry account key — `az cognitiveservices account keys list -g deepdoc-main -n deepdoc-foundry` |
| `deepdoc-hosted-monthly` (Azure Cost Management budget) | subscription-level | Spend guardrail, ₹4,831/mo (≈$50 at time of setup), alerts at 50/80/100% actual + forecasted | n/a — alerts go to `pranavisverysad@gmail.com` |
| **Cloudflare Pages project `deepdoc`** (single project, both domains) | Cloudflare account | Everything Cloudflare-side: marketing site (static) + hosted app (SSR, `web/src/pages/cloud/`) — OAuth, repo picker, **enqueue dispatch**, status/project management, vanity-URL site proxy. **Replaces the retired `deepdoc-hosted` Worker (2026-07-25).** | `wrangler pages secret put --project-name=deepdoc` — `GITHUB_CLIENT_ID`, `GITHUB_SECRET_ID`, `QUEUE_MESSAGES_URL` (queue `/messages` endpoint + add-SAS) |
| D1 `deepdoc-hosted-db` (id `ba724999-e3e3-4eb3-bfed-9d85f49dd01e`) | Cloudflare account | Sessions, projects, quotas, OAuth CSRF state, owner/repo→job lookup | n/a — no external creds; bound to the Pages project via `web/wrangler.toml` |
| R2 bucket `deepdoc-hosted-sites` | Cloudflare account | **Durable copy of every finished site** (`{owner}/{repo}/…`) **and job status** (`jobs/{id}/status.json`). The Job uploads both; the Pages Function serves sites and reads status straight from R2 — no compute to poll. | R2 API token (Object Read & Write, scoped to this bucket) — `R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` as Job secrets |
| ~~`deepdoc-runner`~~ (old always-on Container App) | — | **RETIRED 2026-07-24** — replaced by the event-driven Job. Deleted to stop the ~$10/mo idle charge. | — |
| ~~Worker `deepdoc-hosted`~~ | — | **RETIRED 2026-07-25** — merged into the `deepdoc` Pages project above. `cloud.deepdoc.tech` was detached from this Worker (via the Workers custom-domains API) and re-attached to the Pages project as a second custom domain. | — |
| `deepdoc.tech` + `cloud.deepdoc.tech` (Pages custom domains) | Cloudflare zone `deepdoc.tech` | Public entry points — both on the same Pages project now | n/a |
| GitHub OAuth App `DeepDoc Cloud (Production)` | github.com/settings/developers | Login for the hosted flow | Client ID/Secret — `wrangler pages secret put` (`GITHUB_CLIENT_ID`/`GITHUB_SECRET_ID`) |

**Cutover mechanics (2026-07-25, for reference):** Cloudflare Pages doesn't
expose custom-domain management via `wrangler` CLI in this version, and a
hostname can only be bound to one resource (Worker *or* Pages project) at a
time. Cutover was: (1) `DELETE
/accounts/{acct}/workers/domains/{domain_id}` to detach `cloud.deepdoc.tech`
from the old Worker, (2) `POST
/accounts/{acct}/pages/projects/deepdoc/domains` to attach it to the Pages
project, both via the Cloudflare REST API directly (using wrangler's own
stored OAuth token as a Bearer token — `~/Library/Preferences/.wrangler/config/default.toml`
on macOS) since the CLI has no equivalent command. A Worker custom domain
auto-manages its own DNS record as part of its lifecycle; detaching it
**removes that DNS record**, so the new Pages custom domain needs its own
CNAME added afterward if Cloudflare's same-account auto-provisioning doesn't
pick it up immediately.

## Accounts & per-site visibility (added later)

- **Account view** at `/account` (SPA route, app shell served by the Worker):
  identity, quota usage, and **Log out** (`POST /api/logout` — deletes the D1
  session row and expires the `dd_session` cookie). Re-login is the normal
  GitHub OAuth flow and can land on a different account.
- **Every generated site has a visibility** (`private` | `public`), stored on
  both `projects.visibility` (per-user dashboard control) and
  `owner_repo_jobs.visibility` (the serving authority). New generations default
  **private**; existing sites were backfilled `public`. Users toggle it from the
  dashboard via `POST /api/projects/:owner/:repo/visibility`.
- **`owner_repo_jobs.owner_login`** records the single DeepDoc user who owns each
  repo's site (set once, first generation wins). `handleGenerate` refuses (409) a
  second user trying to generate a repo someone else already owns — one canonical
  site per repo.
- **Private-site enforcement is server-side in the Worker** (`handleOwnerRepoSite`):
  before serving *any* byte — including `/_next/*` assets — a private site
  requires a session whose login matches `owner_login`, else a 403 "private"
  page. This is a real trust boundary because the R2 bucket is not publicly
  exposed; the Worker binding is the only read path. Verified in production:
  anon + wrong-user blocked (403) on both HTML and asset paths, owner served,
  public sites unaffected.

**Orphaned from an earlier abandoned plan**: an AWS Budget
(`deepdoc-hosted-monthly`, $20/month) exists from a prior AWS-based
architecture that was scrapped before any AWS resources were created. No AWS
resources back this deployment — safe to delete that budget alert whenever
convenient, it's not load-bearing.

## Dispatch flow (how a generation runs)

1. Worker `handleGenerate` mints a `job_id`, writes D1 bookkeeping, and
   **enqueues** `{job_id, owner, repo, github_token, visibility}` (base64-JSON)
   onto `deepdoc-jobs` via `QUEUE_MESSAGES_URL` (queue REST + add-SAS).
2. KEDA (built into Container Apps) sees the queue length and starts a
   `deepdoc-gen-job` execution — its own isolated 4 vCPU / 8 GiB container.
3. `job.py` dequeues the one message (1-hr visibility lease), runs the shared
   `pipeline.py` (clone → `deepdoc generate` → `deepdoc deploy`), uploads the
   site + `jobs/{id}/status.json` to R2, then (since 2026-08-27, `deepdoc-runner:v9`)
   calls `pipeline.notify_completion()` — a best-effort
   `POST /api/internal/reconcile` telling Cloudflare a terminal status now
   exists in R2 — before deleting the message and exiting.
4. The Worker reads status from `jobs/{id}/status.json` and serves the site
   from R2 — it never talks to a container directly.

## D1 status reconciliation (added 2026-08-27)

`projects.status` in D1 is a **copy** of the real status in R2
(`jobs/{id}/status.json`); it existed only to make `GET /api/projects` and the
dashboard cheap to render. The one thing that refreshed that copy used to be
`GET /api/projects` itself — scoped to the calling user's own rows, and only
when they happened to load the page. A job whose owner never looked again
left its row wrong forever. Found live: `usestrix/strix`, `laluka-osk`'s
`shopware/shopware`, and `tss-pranavkumar/orgraph` sat stale from 9 minutes to
28 days — two of the three had actually finished successfully.

Two pieces fix this:

- **`POST /api/internal/reconcile`** (`web/src/pages/cloud/api/internal/reconcile.ts`) —
  auth'd by the `RECONCILE_SECRET` shared secret (`X-Reconcile-Secret` header;
  set via `wrangler pages secret put` on the Cloudflare side and as a
  Container App Job secret named `reconcile-secret` on the Azure side —
  **the same value on both**, no key exchange protocol). Sweeps every
  `projects` row not in `('done','failed')`, re-reads `fetchJobStatus` for
  each, writes back whatever changed. Same logic `api/projects/index.ts`
  already had, just not scoped to one user. Capped at 100 rows/call
  (`ORDER BY created_at ASC`, oldest first) so a large backlog drains over
  a few calls rather than one slow request.
  - Requires `Content-Type` (or an `Origin` header) on the POST — Astro's
    default CSRF `checkOrigin` protection 403s a bare POST with neither. Not
    specific to this route: `POST /api/logout` hits the same wall from curl.
  - **Manual trigger** (debug, or to force an immediate sweep):
    ```bash
    curl -X POST https://cloud.deepdoc.tech/api/internal/reconcile \
      -H "X-Reconcile-Secret: $(cat <secret>)" -H "Content-Type: application/json"
    ```
- **`pipeline.notify_completion()`** (`hosted-runner/pipeline.py`) — the real
  fix, called from `job.py`'s `main()` right after `run_generation` returns
  (`result['status']` is always terminal there). Pings the endpoint above so
  Cloudflare corrects D1 within seconds of a job finishing, instead of
  whenever (if ever) someone happens to look. Deliberately a bare "go check
  R2" ping rather than `{job_id, status}` — no payload contract to keep in
  sync between the two sides, one shared idea of "the truth is in R2." No-ops
  silently if `RECONCILE_SECRET` isn't set (local dev) or the call fails
  (network blip) — same best-effort contract as `write_status()`; a stale D1
  row is a UI inconvenience, re-running a whole generation because a
  notification ping failed would not be a fair trade.

An earlier draft of this fix was a standalone Container Apps Job polling the
sweep endpoint on a 15-minute cron. Scrapped once it was clear the runner
container can just tell Cloudflare directly the moment it knows — push beats
poll here: zero staleness window instead of up to 15 minutes, and zero
recurring compute cost instead of a job running every 15 minutes forever.
Confirmed (empirically, via the Pages project's own config API, not from
memory) that Cloudflare Pages has no native Cron Triggers — if a
poll-based fallback is ever needed again, it has to live on the Azure side.

The sweep endpoint remains useful on its own even with the push in place: it
catches anything that finished before `v9`, any ping that failed to land, and
serves as the manual escape hatch above.

## Maintenance / inspection commands

**Job executions / logs:**
```bash
az containerapp job execution list -n deepdoc-gen-job -g deepdoc-main -o table
az monitor log-analytics query -w <workspace-id> \
  --analytics-query "ContainerAppConsoleLogs_CL | where ContainerGroupName_s startswith 'deepdoc-gen-job' | order by TimeGenerated desc | take 50"
# stop a stuck/lingering execution (see the KEDA note below):
az containerapp job stop -n deepdoc-gen-job -g deepdoc-main --job-execution-name <exec-name>
```

**Redeploy a new job image version:**
```bash
cd /path/to/codewiki
az acr build -r deepdocacr -t deepdoc-runner:v6 -f hosted-runner/Dockerfile .
az containerapp job update -n deepdoc-gen-job -g deepdoc-main --image deepdocacr.azurecr.io/deepdoc-runner:v6
```
`--image` only swaps the image; existing secrets/env vars (`reconcile-secret`
→ `RECONCILE_SECRET` included) survive across this. Only needed once, when
`reconcile-secret` doesn't exist yet:
```bash
az containerapp job secret set -n deepdoc-gen-job -g deepdoc-main --secrets "reconcile-secret=<value>"
az containerapp job update -n deepdoc-gen-job -g deepdoc-main --set-env-vars "RECONCILE_SECRET=secretref:reconcile-secret"
```
If `RECONCILE_SECRET` is ever rotated, update it in **both** places — it must
be the same value on the Cloudflare Pages secret (`wrangler pages secret put
RECONCILE_SECRET`) and this Container App Job secret, or `notify_completion()`
silently 401s (best-effort — it won't surface as a job failure, just as D1
drifting stale again).

**Manually enqueue a job** (debug — base64 the JSON to match `job.py`):
```bash
CONN=$(az storage account show-connection-string -g deepdoc-main --name deepdocjobs --query connectionString -o tsv)
B64=$(python3 -c 'import base64,json;print(base64.b64encode(json.dumps({"job_id":"dbg1","owner":"o","repo":"r","github_token":None,"visibility":"public"}).encode()).decode())')
az storage message put --queue-name deepdoc-jobs --content "$B64" --connection-string "$CONN"
```

**Inspect D1 / job status:**
```bash
cd web/hosted
npx wrangler d1 execute deepdoc-hosted-db --remote --command "SELECT * FROM projects ORDER BY created_at DESC LIMIT 20"
npx wrangler r2 object get deepdoc-hosted-sites/jobs/<job_id>/status.json --remote --pipe
```

**Rotate the queue SAS the Worker uses** (regen add-SAS → set the Worker secret;
no Azure-side coordination needed since it's read via the connection string):
```bash
CONN=$(az storage account show-connection-string -g deepdoc-main --name deepdocjobs --query connectionString -o tsv)
SAS=$(az storage queue generate-sas --name deepdoc-jobs --account-name deepdocjobs --permissions a --expiry 2029-01-01T00:00:00Z --https-only --connection-string "$CONN" -o tsv)
echo "https://deepdocjobs.queue.core.windows.net/deepdoc-jobs/messages?${SAS}" | npx wrangler secret put QUEUE_MESSAGES_URL  # then wrangler deploy
```

**Redeploy the Worker:** `cd web/hosted && npx wrangler deploy`

**Tear down everything** (dependency order):
```bash
az containerapp job delete -n deepdoc-gen-job -g deepdoc-main --yes
az containerapp env delete -n deepdoc-runner-env -g deepdoc-main --yes
az acr delete -n deepdocacr --yes
az storage account delete -n deepdocjobs -g deepdoc-main --yes
npx wrangler delete deepdoc-hosted          # from web/hosted/
npx wrangler d1 delete deepdoc-hosted-db
npx wrangler r2 bucket delete deepdoc-hosted-sites
```

## Known limitations (accepted for this pass)

- **KEDA can start an extra no-op execution.** Because it polls queue length on
  an interval, a single message can occasionally trigger a second execution
  before the first has leased it. Only one execution can lease/process a given
  message (atomic), so **there's never duplicate generation** — the extra one
  finds an empty queue and exits. Rarely one lingers `Running`; stop it with
  `az containerapp job stop` (it's billable while up). Not worth engineering
  away at this scale, but watch it if you see idle cost.
- The GitHub token rides in the queue message (private queue, deleted after
  processing) — same trust level as the prior HTTPS dispatch; a token-broker is
  future work.
- No Key Vault — secrets are Container App Job / Worker secrets.
- No automated cleanup of expired D1 sessions/oauth_states beyond the inline
  login-time cleanup, of `jobs/{id}/status.json` objects, or of R2 site objects
  when a project is deleted (delete only removes the D1 bookkeeping row).
- **Foundry `DeepSeek-V4-Flash` quota is the real concurrency ceiling, not
  Container Apps.** The env's core quota is 100 (10 executions × 4 vCPU max
  10), plenty for several concurrent generations. But the deployment is
  capped at 250 RPM / 250K TPM, `max_parallel_workers: 6` per generation, and
  a single large-repo classify prompt can burn well over half that in one
  call. `MAX_RETRIES = 3` on a 429 with backoff capped at 20s
  (`deepdoc/generator/generation.py`), and `deepdoc deploy` refuses the whole
  site if even one page failed — so sustained throttling under concurrent
  load doesn't degrade gracefully, it kills the site outright. This is how
  `shopware/shopware` failed (`stub docs present: core`). Honest concurrent
  capacity today is 2-3 simultaneous generations, not the 6-7 the compute
  ceiling would suggest. Raising the Flash deployment's capacity, or
  spreading load across `DeepSeek-V4-Flash-0731` / `gpt-5-mini` (both
  provisioned on `deepdoc-foundry` already, far higher TPM), is the fix if
  concurrent usage grows.
- **No per-user concurrency gate.** `api/generate.ts` only enforces per-repo
  dedup, `MAX_SAVED_PROJECTS = 2`, and `MAX_STARTS_PER_DAY = 2` — a user can
  start two different repos at once and both generate in parallel. Verified
  live: `laluka-osk` holds exactly two projects, both self-started
  concurrently.
