import type { APIRoute } from "astro";
import { requireSession } from "../../../lib/hosted/session";

// Ported from handleRepos in web/hosted/src/index.ts.
export const GET: APIRoute = async ({ locals, cookies }) => {
  const user = await requireSession(locals.runtime.env, cookies);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const reposRes = await fetch(
    "https://api.github.com/user/repos?affiliation=owner&sort=updated&per_page=100",
    { headers: { Authorization: `Bearer ${user.token}`, "User-Agent": "deepdoc-hosted" } },
  );
  if (!reposRes.ok) {
    return new Response(JSON.stringify({ error: "failed to list repos", detail: await reposRes.text() }), {
      status: 502,
    });
  }
  const repos = (await reposRes.json()) as Array<{
    full_name: string;
    name: string;
    owner: { login: string; avatar_url: string };
    private: boolean;
    updated_at: string;
    description: string | null;
    language: string | null;
  }>;
  const simplified = repos.map((r) => ({
    fullName: r.full_name,
    owner: r.owner.login,
    repo: r.name,
    private: r.private,
    updatedAt: r.updated_at,
    description: r.description,
    language: r.language,
    avatarUrl: r.owner.avatar_url,
  }));
  return new Response(JSON.stringify(simplified), { headers: { "Content-Type": "application/json" } });
};
