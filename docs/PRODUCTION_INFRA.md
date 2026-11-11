# Production infrastructure — hosted generation ("Try DeepDoc")

Maintenance reference for the infrastructure behind the hosted "generate docs
from a GitHub repo, no CLI" flow at **cloud.deepdoc.tech**. `AGENTS.md`'s
"Hosted-generation" section covers the code and local dev setup this deploys
from (`web/` + `hosted-runner/`).

## History in one paragraph

Until October 2026 the generation compute and LLM ran on Azure (a Container Apps
Job fed by a Storage Queue, models on Azure AI Foundry). That subscription was
disabled (state `Warned`, read-only), which took generation down while the
Cloudflare side kept serving. **Generation now runs on AWS (ECS Fargate +
Bedrock). Cloudflare is unchanged and still owns the app, database and stored
sites.** The old Azure resources are not used. A new, small Azure Foundry account
(`deepdoc-foundry-e2`, see below) provides the LLM only.

## Resource inventory

### Cloudflare (unchanged)

| Resource | Purpose | Credential |
|---|---|---|
| Pages project `deepdoc` | Marketing site (static) and the hosted app (SSR, `web/src/pages/cloud/`): OAuth, repo picker, dispatch, status, vanity-URL site proxy. Custom domains `deepdoc.tech` and `cloud.deepdoc.tech` | Pages secrets, below |
| D1 `deepdoc-hosted-db` (`ba724999-e3e3-4eb3-bfed-9d85f49dd01e`) | Sessions, projects, quotas, OAuth state, owner/repo to job lookup | bound via `web/wrangler.toml` |
| R2 `deepdoc-hosted-sites` | Every finished site (`{owner}/{repo}/…`), job status (`jobs/{id}/status.json`) and, briefly, job input (`jobs/{id}/input.json`) | R2 S3 token, see AWS secrets |
| GitHub OAuth App `DeepDoc Cloud (Production)` | Login | `GITHUB_CLIENT_ID` / `GITHUB_SECRET_ID` |

Pages secrets (`wrangler pages secret put <NAME> --project-name=deepdoc`):
`GITHUB_CLIENT_ID`, `GITHUB_SECRET_ID`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY` (the `deepdoc-dispatch` IAM user), `RECONCILE_SECRET`.
Pages plain vars live in `web/wrangler.toml` `[vars]`: `AWS_REGION`,
`ECS_CLUSTER`, `ECS_TASK_DEFINITION`, `ECS_SUBNETS`, `ECS_SECURITY_GROUP`, and the
kill switch `GENERATION_PAUSED` (`"1"` makes `POST /api/generate` return 503 instead
of starting a job, shows a "generation is paused" notice on every app screen via
`/api/me`, and swaps the generate form for a paused message; set it while the runner
or its LLM is down, remove it and redeploy to go live). Unknown URLs on
`cloud.deepdoc.tech` serve styled pages (`[...rest].ts`, `notFoundSitePage`), never
Astro's bare 404.
The old `AZURE_*` and `QUEUE_MESSAGES_URL` Pages secrets are unused and can be
deleted (`wrangler pages secret delete <NAME> --project-name=deepdoc`).
Pages binds secrets at deploy time: **redeploy after changing one**.

### AWS (account `746244690345`, `us-east-1`)

Created and refreshed by `hosted-runner/aws/provision.sh` (idempotent).

| Resource | Purpose |
|---|---|
| ECR repo `deepdoc-runner` | The runner image (linux/arm64). `hosted-runner/aws/deploy-image.sh [tag]` builds and pushes it. Keeps the last 5 images. |
| ECS cluster `deepdoc` + task definition `deepdoc-gen` | One Fargate task per generation: **ARM64, 4 vCPU / 8 GiB, 40 GiB scratch**, `python job.py`. Idle cost is zero. |
| Role `deepdoc-ecs-execution` | Pulls the image, writes logs, reads `/deepdoc/*` SSM parameters. |
| Role `deepdoc-gen-task` | What the generation code may do: invoke Bedrock models, nothing else. |
| Security group `deepdoc-gen-egress` | Egress only, no inbound. Tasks use the default VPC with a public IP, so there is no NAT charge. |
| Log group `/deepdoc/gen` | Task output, 14-day retention. |
| IAM user `deepdoc-dispatch` | Used only by the Pages app: `ecs:RunTask` on `deepdoc-gen`, `ecs:StopTask`/`DescribeTasks` in the cluster, `iam:PassRole` for the two roles. `hosted-runner/aws/dispatch-key.sh <file>` rotates its key into a 0600 file without printing it. |
| SSM SecureStrings `/deepdoc/azure-api-key`, `/deepdoc/r2-access-key-id`, `/deepdoc/r2-secret-access-key`, `/deepdoc/reconcile-secret` | Injected into the task as env vars. Set them with `aws ssm put-parameter --type SecureString --overwrite`. |

LLM (since 2026-11-11): **`gpt-oss-120b` on Azure AI Foundry**, called from the AWS
task with an API key, because Bedrock quota on this AWS account is 0. The Azure
side is one resource group `deepdoc-rg` (eastus2) holding the AIServices account
`deepdoc-foundry-e2` and a `gpt-oss-120b` deployment (GlobalStandard, 200K TPM). It
costs nothing while idle. The key lives in SSM `/deepdoc/azure-api-key` and is
injected as `AZURE_API_KEY`. DeepSeek-V4-Flash was the preferred model but had zero
Azure quota in every region checked. The model and its capability numbers are
task-definition env vars (`DEEPDOC_LLM_MODEL`, `_PROVIDER`, `_API_KEY_ENV`,
`_BASE_URL`, `_API_VERSION`, `_CONTEXT_TOKENS`, `_OUTPUT_RESERVE_TOKENS`); changing
the model is `provision.sh` with different env, not a code change. To rotate the
Azure key, re-run `az cognitiveservices account keys list` into
`aws ssm put-parameter --overwrite`; new tasks pick it up.

**Spend limit: about $10 total.** AWS budget `deepdoc-hosted-monthly` is $10 with
50/80/100% email alerts, but budgets only alert. The real brakes are the
per-generation cap (`DEEPDOC_MAX_USD`, 0.50 in the task definition), the per-user
limits in `api/generate.ts`, and `GENERATION_PAUSED`.

## Dispatch flow (how a generation runs)

1. `api/generate.ts` mints a `job_id`, writes `jobs/{id}/input.json`
   (`{job_id, owner, repo, github_token, visibility}`) to R2, then calls ECS
   `RunTask` (SigV4, `web/src/lib/hosted/aws.ts`) passing only `JOB_ID`. The token
   is deliberately not in the `RunTask` call: that call is recorded in CloudTrail
   and in the task description.
2. The Fargate task (`hosted-runner/job.py`) reads and **deletes** the input
   object, then runs `pipeline.py`: preflight cost estimate, clone,
   `deepdoc generate`, `deepdoc deploy`, upload the site to R2, write
   `jobs/{id}/status.json` (including the task ARN as `execution_name`).
3. On any terminal state it calls `pipeline.notify_completion()`, which pings
   `POST /api/internal/reconcile` so D1 matches R2 within seconds.
4. The Pages app reads status from R2 and serves sites from R2. It never talks to
   a running container. Deleting a project stops the task via `StopTask`.

### Per-generation cost cap

`DEEPDOC_MAX_USD` (code default `1.00`; the task definition sets `0.50`) is enforced
twice. First verified end to end on 2026-11-11: `kennethreitz/records` (22 files,
16 pages) generated, built and uploaded in about 6.5 minutes, status `done`.

- **Preflight** (`pipeline.preflight_estimate`): estimates source tokens from the
  clone and refuses a repo whose estimated cost is over the cap. The multipliers
  (`DEEPDOC_EST_INPUT_MULT`, `DEEPDOC_EST_OUTPUT_MULT`) are heuristics and have
  **not yet been calibrated against a real run**.
- **Hard stop** (`hosted-runner/budget/sitecustomize.py`): every `deepdoc`
  subprocess wraps `litellm.completion`, prices real token usage from
  `DEEPDOC_PRICE_IN_PER_M` / `DEEPDOC_PRICE_OUT_PER_M` (defaults are
  gpt-oss-120b on Bedrock: 0.15 / 0.60) and exits with code 75 when spend passes
  the cap. If you change the model, change the prices too, or the cap measures the
  wrong thing.

## Accounts and per-site visibility

- **Every generated site has a visibility** (`private` | `public`), stored on
  `projects.visibility` (dashboard control) and `owner_repo_jobs.visibility` (the
  serving authority). New generations default to **private**.
- **`owner_repo_jobs.owner_login`** records the single DeepDoc user who owns each
  repo's site (first generation wins); `api/generate.ts` refuses (409) a second
  user.
- **Private-site enforcement is server-side** in the site proxy
  (`web/src/pages/cloud/[owner]/[repo]/[...path].ts`): before serving any byte,
  including `/_next/*` assets, a private site requires a session whose login
  matches `owner_login`. The R2 bucket is not public, so this endpoint is the
  only read path.

## D1 status reconciliation

`projects.status` in D1 is a copy of the real status in R2. The task pings
`POST /api/internal/reconcile` (`web/src/pages/cloud/api/internal/reconcile.ts`,
authenticated by the `X-Reconcile-Secret` header) when a job ends; it sweeps every
`projects` row not in `('done','failed')`, re-reads R2, and writes back changes
(100 rows per call, oldest first). `RECONCILE_SECRET` must be the **same value**
on the Pages secret and the SSM parameter `/deepdoc/reconcile-secret`, or the ping
silently 401s and D1 drifts stale again (the job itself still succeeds).
Manual sweep:

```bash
curl -X POST https://cloud.deepdoc.tech/api/internal/reconcile \
  -H "X-Reconcile-Secret: $SECRET" -H "Content-Type: application/json"
```

## Maintenance commands

```bash
# Re-apply AWS infra (idempotent) / rebuild and push the runner image
hosted-runner/aws/provision.sh
hosted-runner/aws/deploy-image.sh

# Run a task by hand (needs jobs/<id>/input.json in R2 first)
aws ecs run-task --cluster deepdoc --task-definition deepdoc-gen --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet>],securityGroups=[<sg>],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"runner","environment":[{"name":"JOB_ID","value":"dbg1"}]}]}'

# Watch / list / stop
aws logs tail /deepdoc/gen --follow
aws ecs list-tasks --cluster deepdoc
aws ecs stop-task --cluster deepdoc --task <arn>

# Set a secret the task reads
aws ssm put-parameter --name /deepdoc/r2-access-key-id --type SecureString --overwrite --value "<value>"

# Inspect D1 / job status
cd web
npx wrangler d1 execute deepdoc-hosted-db --remote --command "SELECT * FROM projects ORDER BY created_at DESC LIMIT 20"
npx wrangler r2 object get deepdoc-hosted-sites/jobs/<job_id>/status.json --remote --pipe

# Redeploy the Pages app (after `bun run build`)
npx wrangler pages deploy dist --project-name=deepdoc
```

**Tear down the AWS side:** delete the ECS cluster and task definitions, the ECR
repo, the `/deepdoc/*` SSM parameters, the `/deepdoc/gen` log group, the two task
roles, the `deepdoc-dispatch` user and the `deepdoc-gen-egress` security group.

## Known limitations

- **Bedrock inference quota can be zero on a new account.** On 2026-10-24 and again
  on 2026-11-11 every on-demand model on this account had a daily-token quota of 0
  (non-adjustable through Service Quotas), so every call failed with
  `ThrottlingException: Too many tokens per day`. It needs an AWS Support case to
  raise. That is why the LLM is on Azure Foundry for now.
- **Azure price for `gpt-oss-120b` is unconfirmed.** `DEEPDOC_PRICE_*` still holds the
  0.15 / 0.60 per-million defaults; check the Azure rate and update them so the hard
  cap measures real spend. Actual cost of the first test run was not measured.
- **Test leftovers in R2:** the 2026-11-11 test run wrote `kennethreitz/records/…` and
  `jobs/test-1794398450/status.json`. No D1 row points at them so nothing serves them;
  delete whenever convenient.
- **Fargate quota** is 30 on-demand vCPUs (7 concurrent 4-vCPU tasks).
- **No per-user concurrency gate.** `api/generate.ts` only enforces per-repo
  dedup, `MAX_SAVED_PROJECTS = 2` and `MAX_STARTS_PER_DAY = 2`.
- **No automated cleanup** of expired D1 sessions, `jobs/{id}/status.json`
  objects, or R2 site objects when a project is deleted (delete removes only the
  D1 row).
- **`deepdoc deploy` refuses the whole site if one page failed**, so a throttled
  or capped run fails outright instead of degrading. This is how
  `shopware/shopware` failed on the old Azure setup.
