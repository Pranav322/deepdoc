/// <reference types="astro/client" />
/// <reference types="@cloudflare/workers-types" />
import type { Runtime } from "@astrojs/cloudflare";

type CloudEnv = {
  DB: D1Database;
  SITES: R2Bucket;
  GITHUB_CLIENT_ID: string;
  GITHUB_SECRET_ID: string;
  // AWS ECS Fargate dispatch (see lib/hosted/aws.ts). The key pair belongs to the
  // deepdoc-dispatch IAM user, which can only RunTask/StopTask in one cluster.
  AWS_ACCESS_KEY_ID: string;
  AWS_SECRET_ACCESS_KEY: string;
  AWS_REGION: string;
  ECS_CLUSTER: string;
  ECS_TASK_DEFINITION: string;
  ECS_SUBNETS: string;
  ECS_SECURITY_GROUP: string;
  // "1" refuses new generations with a 503 (set in wrangler.toml [vars]).
  GENERATION_PAUSED?: string;
  // Shared secret for POST /api/internal/reconcile — see that route for why
  // it exists (D1 job status otherwise only self-heals when the owning user
  // happens to load /api/projects).
  RECONCILE_SECRET: string;
};

declare global {
  namespace App {
    interface Locals extends Runtime<CloudEnv> {}
  }
}
