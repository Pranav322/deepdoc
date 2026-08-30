// Copy the static export into web/public/docs/. Astro serves public/
// verbatim, so the site lands at /docs with no routing config — the
// marketing pages and the hosted-app endpoints stay untouched.
import { cp, rm, mkdir, access } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
// With a custom distDir, `output: export` writes the exported site into the
// dist directory itself rather than into out/. The build passes EXPORT_DIR so
// this does not have to guess.
const out = resolve(here, '..', process.env.EXPORT_DIR || 'out');
const dest = resolve(here, '..', '..', 'public', 'docs');

try { await access(out); } catch {
  console.error(`[docs] no ${out} — run \`npm run build\` first`);
  process.exit(1);
}
await rm(dest, { recursive: true, force: true });
await mkdir(dirname(dest), { recursive: true });
await cp(out, dest, { recursive: true });
await flattenBracketDirs(dest);
console.log(`[docs] copied static export -> ${dest}`);

/**
 * Next names its route chunks after the route, so a catch-all produces a
 * directory literally called `[[...slug]]` under `(docs)/`. The Astro
 * Cloudflare adapter globs public/ to build _routes.json, reads those brackets
 * as an Astro dynamic-route parameter, and dies with
 * "Parameter name must match /^[a-zA-Z0-9_$]+$/" — taking the whole marketing
 * build down with it.
 *
 * Rename the offending segments to plain names and rewrite the references. The
 * files are content-hashed and referenced by URL only, so the name is free to
 * change.
 */
async function flattenBracketDirs(root) {
  const { readdir, rename, readFile, writeFile } = await import('node:fs/promises');
  const { join, relative } = await import('node:path');
  const renames = [];

  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const full = join(dir, entry.name);
      await walk(full);
      if (/[[\]()]/.test(entry.name)) {
        const safe = entry.name.replace(/[^a-zA-Z0-9_-]/g, '') || 'route';
        const target = join(dir, safe);
        await rename(full, target);
        renames.push([entry.name, safe]);
      }
    }
  }
  await walk(root);
  if (!renames.length) return;

  // Rewrite every reference, in both raw and URL-encoded form.
  const files = [];
  async function collect(dir) {
    for (const e of await readdir(dir, { withFileTypes: true })) {
      const full = join(dir, e.name);
      if (e.isDirectory()) await collect(full);
      else if (/\.(html|js|txt|json)$/.test(e.name)) files.push(full);
    }
  }
  await collect(root);

  for (const file of files) {
    let text = await readFile(file, 'utf-8');
    let changed = false;
    for (const [from, to] of renames) {
      for (const variant of [from, encodeURIComponent(from)]) {
        if (text.includes(variant)) {
          text = text.split(variant).join(to);
          changed = true;
        }
      }
    }
    if (changed) await writeFile(file, text);
  }
  console.log(`[docs] flattened ${renames.length} bracketed chunk dir(s) for the Cloudflare adapter`);
}
