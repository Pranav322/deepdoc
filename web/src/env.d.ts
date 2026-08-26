/// <reference types="astro/client" />
/// <reference types="@cloudflare/workers-types" />
import type { Runtime } from "@astrojs/cloudflare";

type CloudEnv = {
  DB: D1Database;
  SITES: R2Bucket;
  GITHUB_CLIENT_ID: string;
  GITHUB_SECRET_ID: string;
  QUEUE_MESSAGES_URL: string;
  AZURE_TENANT_ID: string;
  AZURE_CLIENT_ID: string;
  AZURE_CLIENT_SECRET: string;
  AZURE_SUBSCRIPTION_ID: string;
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
