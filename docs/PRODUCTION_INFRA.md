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
   site + `jobs/{id}/status.json` to R2, deletes the message, exits.
4. The Worker reads status from `jobs/{id}/status.json` and serves the site
   from R2 — it never talks to a container directly.

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
