// Lets the Worker stop a runaway/hung generation directly via the Azure
// Container Apps Management API, instead of only deleting the D1 row (which
// left compute running for hours after a project was "deleted" — see the
// openclaw/openclaw incident). Auth is client-credentials against a service
// principal scoped ONLY to the deepdoc-gen-job resource (Container Apps
// Contributor role) — see AZURE_CLIENT_ID/AZURE_CLIENT_SECRET secrets.

export interface AzureEnv {
  AZURE_TENANT_ID: string;
  AZURE_CLIENT_ID: string;
  AZURE_CLIENT_SECRET: string;
  AZURE_SUBSCRIPTION_ID: string;
}

const RESOURCE_GROUP = "deepdoc-main";
const JOB_NAME = "deepdoc-gen-job";

async function getAzureToken(env: AzureEnv): Promise<string> {
  const res = await fetch(`https://login.microsoftonline.com/${env.AZURE_TENANT_ID}/oauth2/v2.0/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: env.AZURE_CLIENT_ID,
      client_secret: env.AZURE_CLIENT_SECRET,
      scope: "https://management.azure.com/.default",
    }),
  });
  if (!res.ok) throw new Error(`azure token request failed: ${res.status} ${await res.text()}`);
  const data = await res.json<{ access_token: string }>();
  return data.access_token;
}

// Best-effort — a stop failure (e.g. execution already finished) must never
// block the actual delete of the user's project record.
export async function stopJobExecution(env: AzureEnv, executionName: string): Promise<void> {
  try {
    const token = await getAzureToken(env);
    const url =
      `https://management.azure.com/subscriptions/${env.AZURE_SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}` +
      `/providers/Microsoft.App/jobs/${JOB_NAME}/executions/${executionName}/stop?api-version=2024-03-01`;
    await fetch(url, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
  } catch {
    // best-effort — deletion proceeds regardless
  }
}
