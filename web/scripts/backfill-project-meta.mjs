// Backfill description/language/stars/avatar_url on existing `projects` rows.
//
// Why this exists: until `api/generate.ts` learned to ask GitHub itself, the
// metadata stored with a project was whatever the browser sent in the POST
// body. The repo-picker path sent real values; the paste-a-URL path sent
// none. So most rows — and therefore most public gallery cards — have a null
// description, language and star count. New generations are fixed at the
// source; this repairs the rows already in D1.
//
// Dry run (default) prints what it would change and writes nothing:
//   node scripts/backfill-project-meta.mjs
// Apply:
//   GITHUB_TOKEN=ghp_... node scripts/backfill-project-meta.mjs --apply
//
// A token is only needed to --apply (and to see real values in a dry run);
// without one GitHub allows 60 requests/hour per IP, which is under the
// number of rows. Any classic token with no scopes is enough for public
// repos. Private repos need `repo`, and rows this token cannot see are
// reported and skipped rather than blanked.
//
// Talks to production D1 through `wrangler d1 execute --remote`, so it needs
// the same wrangler login used to deploy. Run it from web/.
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const DB = "deepdoc-hosted-db";
const APPLY = process.argv.includes("--apply");
const TOKEN = process.env.GITHUB_TOKEN || "";

/** Run one statement against remote D1 and return its rows. */
async function d1(sql) {
  const { stdout } = await execFileAsync(
    "npx",
    ["wrangler", "d1", "execute", DB, "--remote", "--json", "--command", sql],
    { maxBuffer: 32 * 1024 * 1024 },
  );
  // --json emits an array of result envelopes, one per statement.
  const parsed = JSON.parse(stdout);
  const first = Array.isArray(parsed) ? parsed[0] : parsed;
  return first?.results ?? [];
}

function sqlString(v) {
  if (v == null) return "NULL";
  return `'${String(v).replace(/'/g, "''")}'`;
}

async function fetchMeta(owner, repo) {
  const headers = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "deepdoc-backfill",
  };
  if (TOKEN) headers.Authorization = `Bearer ${TOKEN}`;
  const res = await fetch(`https://api.github.com/repos/${owner}/${repo}`, { headers });
  if (res.status === 404) return { gone: true };
  if (res.status === 403 || res.status === 429) {
    throw new Error(
      `GitHub rate-limited this run (${res.status}). ` +
        (TOKEN ? "Wait and re-run." : "Set GITHUB_TOKEN and re-run."),
    );
  }
  if (!res.ok) throw new Error(`GitHub ${res.status} for ${owner}/${repo}`);
  const j = await res.json();
  return {
    description: j.description ?? null,
    language: j.language ?? null,
    stars: j.stargazers_count ?? null,
    avatarUrl: j.owner?.avatar_url ?? null,
  };
}

const rows = await d1(
  `SELECT user_login, owner, repo, description, language, stars, avatar_url
   FROM projects
   WHERE description IS NULL OR language IS NULL OR stars IS NULL OR avatar_url IS NULL
   ORDER BY created_at DESC`,
);

console.log(`${rows.length} project row(s) missing at least one metadata field.`);
if (!rows.length) process.exit(0);
if (!APPLY) console.log("DRY RUN — nothing will be written. Re-run with --apply to commit.\n");
if (!TOKEN) console.log("No GITHUB_TOKEN set: unauthenticated GitHub allows 60 requests/hour.\n");

let updated = 0;
const missing = [];
const failed = [];

for (const row of rows) {
  const name = `${row.owner}/${row.repo}`;
  let meta;
  try {
    meta = await fetchMeta(row.owner, row.repo);
  } catch (err) {
    // A rate-limit is fatal for the run: continuing would just burn through
    // every remaining row producing the same error.
    if (String(err.message).includes("rate-limited")) {
      console.error(`\n${err.message}`);
      break;
    }
    failed.push(`${name} — ${err.message}`);
    continue;
  }
  if (meta.gone) {
    missing.push(name);
    continue;
  }

  // Only fill what is actually absent. A description someone's earlier
  // generation captured is not worth overwriting with a later GitHub read.
  const next = {
    description: row.description ?? meta.description,
    language: row.language ?? meta.language,
    stars: row.stars ?? meta.stars,
    avatar_url: row.avatar_url ?? meta.avatarUrl,
  };
  const changed = Object.entries(next).filter(([k, v]) => v != null && row[k] == null);
  if (!changed.length) continue;

  console.log(
    `${APPLY ? "update" : "would update"} ${name}: ` +
      changed.map(([k, v]) => `${k}=${JSON.stringify(v)?.slice(0, 60)}`).join(", "),
  );

  if (APPLY) {
    await d1(
      `UPDATE projects SET
         description = ${sqlString(next.description)},
         language = ${sqlString(next.language)},
         stars = ${next.stars == null ? "NULL" : Number(next.stars)},
         avatar_url = ${sqlString(next.avatar_url)}
       WHERE user_login = ${sqlString(row.user_login)}
         AND owner = ${sqlString(row.owner)}
         AND repo = ${sqlString(row.repo)}`,
    );
  }
  updated++;
}

console.log(`\n${APPLY ? "Updated" : "Would update"} ${updated} row(s).`);
if (missing.length) {
  console.log(`\n${missing.length} repo(s) GitHub returned 404 for (deleted, renamed, or private to this token) — left untouched:`);
  for (const m of missing) console.log(`  ${m}`);
}
if (failed.length) {
  console.log(`\n${failed.length} row(s) failed:`);
  for (const f of failed) console.log(`  ${f}`);
}
