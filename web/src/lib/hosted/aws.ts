// Starts and stops generation tasks on AWS ECS Fargate from the Cloudflare Pages
// runtime. Requests are signed with SigV4 using the WebCrypto API, so no AWS SDK
// is bundled into the Worker.
//
// The IAM user behind AWS_ACCESS_KEY_ID can do exactly three things: RunTask on
// the deepdoc-gen task definition, StopTask/DescribeTasks in the deepdoc cluster,
// and pass the two task roles. See hosted-runner/aws/provision.sh.

export interface AwsEnv {
  AWS_ACCESS_KEY_ID: string;
  AWS_SECRET_ACCESS_KEY: string;
  AWS_REGION: string;
  ECS_CLUSTER: string;
  ECS_TASK_DEFINITION: string;
  // Comma-separated subnet ids and one security group id.
  ECS_SUBNETS: string;
  ECS_SECURITY_GROUP: string;
}

const enc = new TextEncoder();

function toHex(buf: ArrayBuffer): string {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(data: string): Promise<string> {
  return toHex(await crypto.subtle.digest("SHA-256", enc.encode(data)));
}

async function hmac(key: BufferSource, data: string): Promise<ArrayBuffer> {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return crypto.subtle.sign("HMAC", k, enc.encode(data));
}

async function signedEcsFetch(env: AwsEnv, target: string, body: unknown): Promise<Response> {
  const region = env.AWS_REGION;
  const service = "ecs";
  const host = `ecs.${region}.amazonaws.com`;
  const payload = JSON.stringify(body);
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, ""); // 20260101T000000Z
  const dateStamp = amzDate.slice(0, 8);
  const contentType = "application/x-amz-json-1.1";

  // Headers must be lowercase, sorted by name.
  const canonicalHeaders =
    `content-type:${contentType}\nhost:${host}\nx-amz-date:${amzDate}\nx-amz-target:${target}\n`;
  const signedHeaders = "content-type;host;x-amz-date;x-amz-target";
  const canonicalRequest = ["POST", "/", "", canonicalHeaders, signedHeaders, await sha256Hex(payload)].join("\n");

  const scope = `${dateStamp}/${region}/${service}/aws4_request`;
  const stringToSign = ["AWS4-HMAC-SHA256", amzDate, scope, await sha256Hex(canonicalRequest)].join("\n");

  let key = await hmac(enc.encode(`AWS4${env.AWS_SECRET_ACCESS_KEY}`), dateStamp);
  key = await hmac(key, region);
  key = await hmac(key, service);
  key = await hmac(key, "aws4_request");
  const signature = toHex(await hmac(key, stringToSign));

  return fetch(`https://${host}/`, {
    method: "POST",
    headers: {
      "Content-Type": contentType,
      "X-Amz-Date": amzDate,
      "X-Amz-Target": target,
      Authorization:
        `AWS4-HMAC-SHA256 Credential=${env.AWS_ACCESS_KEY_ID}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`,
    },
    body: payload,
  });
}

// Start one Fargate task for a job. Only the job id travels in the call: the
// input (including the user's GitHub token) is in R2, because RunTask requests are
// recorded in CloudTrail and in the task description.
export async function runGenerationTask(env: AwsEnv, jobId: string): Promise<boolean> {
  try {
    const res = await signedEcsFetch(env, "AmazonEC2ContainerServiceV20141113.RunTask", {
      cluster: env.ECS_CLUSTER,
      taskDefinition: env.ECS_TASK_DEFINITION,
      launchType: "FARGATE",
      count: 1,
      networkConfiguration: {
        awsvpcConfiguration: {
          subnets: env.ECS_SUBNETS.split(",").map((s) => s.trim()).filter(Boolean),
          securityGroups: [env.ECS_SECURITY_GROUP],
          assignPublicIp: "ENABLED",
        },
      },
      overrides: {
        containerOverrides: [{ name: "runner", environment: [{ name: "JOB_ID", value: jobId }] }],
      },
    });
    const json = (await res.json().catch(() => null)) as { failures?: unknown[]; tasks?: unknown[] } | null;
    if (!res.ok || !json || (json.failures && json.failures.length > 0) || !json.tasks?.length) {
      console.error("ecs RunTask failed", res.status, JSON.stringify(json));
      return false;
    }
    return true;
  } catch (err) {
    console.error("ecs RunTask threw", err);
    return false;
  }
}

// Best-effort: a stop failure (task already finished, ARN not yet written) must
// never block deleting the user's project record.
export async function stopGenerationTask(env: AwsEnv, taskArn: string): Promise<void> {
  try {
    await signedEcsFetch(env, "AmazonEC2ContainerServiceV20141113.StopTask", {
      cluster: env.ECS_CLUSTER,
      task: taskArn,
      reason: "project deleted by its owner",
    });
  } catch {
    // deletion proceeds regardless
  }
}
