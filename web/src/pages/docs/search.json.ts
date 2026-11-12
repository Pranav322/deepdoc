export const prerender = true;
import { getCollection } from "astro:content";
import { docsSections, docHref } from "../../lib/nav";

/** Plain text from MDX source: enough for substring search, not for display. */
function plain(src: string): string {
  return src
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\{[^}]*\}/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[`*_>#|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export async function GET() {
  const entries = await getCollection("docs");
  const docs = entries.map((e) => {
    const body = e.body ?? "";
    return {
      id: e.id,
      href: docHref(e.id),
      title: e.data.title,
      section: docsSections.find((s) => s.pages.includes(e.id))?.title ?? "",
      headings: [...body.matchAll(/^#{2,3}\s+(.+)$/gm)].map((m) => m[1].replace(/[`*]/g, "")),
      text: `${e.data.description} ${plain(body)}`.slice(0, 6000),
    };
  });
  return new Response(JSON.stringify(docs), { headers: { "Content-Type": "application/json" } });
}
