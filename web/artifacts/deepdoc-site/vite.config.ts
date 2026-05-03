import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import fs from "fs";
import runtimeErrorOverlay from "@replit/vite-plugin-runtime-error-modal";

type Category = "Added" | "Changed" | "Fixed" | "Maintenance";

interface ReleaseEntry {
  version: string;
  date: string;
  summary: string;
  isLatest?: boolean;
  isPatch?: boolean;
  githubUrl: string;
  sections: { category: Category; items: string[] }[];
}

function formatChangelogDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  const names = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  return `${names[month - 1]} ${day}, ${year}`;
}

function parseChangelog(content: string): ReleaseEntry[] {
  const headerRe = /^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})/gm;
  const hits: { version: string; date: string; index: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = headerRe.exec(content)) !== null) {
    hits.push({ version: m[1], date: m[2], index: m.index });
  }

  return hits.map(({ version, date, index }, i) => {
    const bodyStart = content.indexOf("\n", index) + 1;
    const bodyEnd = i + 1 < hits.length ? hits[i + 1].index : content.length;
    const body = content.slice(bodyStart, bodyEnd).trim();

    const firstSection = body.search(/^### /m);
    const summary = firstSection > 0 ? body.slice(0, firstSection).trim() : "";

    const catRe = /^### (Added|Changed|Fixed|Maintenance)/gm;
    const cats: { category: Category; index: number }[] = [];
    let cm: RegExpExecArray | null;
    while ((cm = catRe.exec(body)) !== null) {
      cats.push({ category: cm[1] as Category, index: cm.index });
    }

    const sections = cats
      .map(({ category, index: ci }, j) => {
        const start = body.indexOf("\n", ci) + 1;
        const end = j + 1 < cats.length ? cats[j + 1].index : body.length;
        const items = body
          .slice(start, end)
          .split("\n")
          .filter((l) => l.startsWith("- "))
          .map((l) => l.slice(2).trim());
        return { category, items };
      })
      .filter((s) => s.items.length > 0);

    const parts = version.split(".").map(Number);
    const isPatch = parts[2] > 0;

    return {
      version: `v${version}`,
      date: formatChangelogDate(date),
      summary,
      isLatest: i === 0,
      ...(isPatch ? { isPatch: true } : {}),
      githubUrl: `https://github.com/tss-pranavkumar/deepdoc/releases/tag/v${version}`,
      sections,
    };
  });
}

const VIRTUAL_ID = "virtual:changelog-data";
const RESOLVED_ID = "\0" + VIRTUAL_ID;

function changelogPlugin(): Plugin {
  const changelogPath = path.resolve(import.meta.dirname, "../../../CHANGELOG.md");
  return {
    name: "changelog-data",
    resolveId(id) {
      if (id === VIRTUAL_ID) return RESOLVED_ID;
    },
    load(id) {
      if (id !== RESOLVED_ID) return;
      this.addWatchFile(changelogPath);
      const content = fs.readFileSync(changelogPath, "utf-8");
      const releases = parseChangelog(content);
      return `export default ${JSON.stringify(releases)};`;
    },
  };
}

const rawPort = process.env.PORT ?? "5173";

const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

const basePath = process.env.BASE_PATH ?? "/";

export default defineConfig({
  base: basePath,
  plugins: [
    react(),
    tailwindcss(),
    runtimeErrorOverlay(),
    changelogPlugin(),
    ...(process.env.NODE_ENV !== "production" &&
    process.env.REPL_ID !== undefined
      ? [
          await import("@replit/vite-plugin-cartographer").then((m) =>
            m.cartographer({
              root: path.resolve(import.meta.dirname, ".."),
            }),
          ),
          await import("@replit/vite-plugin-dev-banner").then((m) =>
            m.devBanner(),
          ),
        ]
      : []),
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
      "@assets": path.resolve(import.meta.dirname, "..", "..", "attached_assets"),
    },
    dedupe: ["react", "react-dom"],
  },
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist/public"),
    emptyOutDir: true,
  },
  server: {
    port,
    strictPort: true,
    host: "0.0.0.0",
    allowedHosts: true,
    fs: {
      strict: true,
    },
  },
  preview: {
    port,
    host: "0.0.0.0",
    allowedHosts: true,
  },
});
