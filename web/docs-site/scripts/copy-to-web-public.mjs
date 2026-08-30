// Copies the static export into web/public/docs/ so the Astro site serves it
// at /docs. Astro copies public/ verbatim, so no routing config is needed and
// the marketing site + hosted app stay untouched.
import { cp, rm, mkdir, access } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, '..', 'out');
const dest = resolve(here, '..', '..', 'public', 'docs');

try {
  await access(out);
} catch {
  console.error('[docs] no out/ — run `next build` first');
  process.exit(1);
}

await rm(dest, { recursive: true, force: true });
await mkdir(dirname(dest), { recursive: true });
// The export already contains a /docs subtree from basePath; copy its
// contents up so public/docs/index.html is the docs root.
await cp(resolve(out, 'docs'), dest, { recursive: true });
await cp(resolve(out, '_next'), resolve(dest, '_next'), { recursive: true });
console.log(`[docs] copied static export -> ${dest}`);
