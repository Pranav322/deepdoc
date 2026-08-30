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
console.log(`[docs] copied static export -> ${dest}`);
