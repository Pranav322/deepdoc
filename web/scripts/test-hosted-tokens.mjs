// The hosted app (src/lib/hosted/page_html.ts) is an HTML string built in a
// Worker, so it cannot import a stylesheet the way an Astro page does. Instead
// it inlines src/styles/tokens.css through a Vite raw import, which means the
// palette cannot drift between deepdoc.tech, /docs and cloud.deepdoc.tech.
//
// This guards that arrangement: the import must exist and be interpolated into
// both stylesheets, no second palette may creep back in, and the tokens file
// must stay safe to embed in a JavaScript template literal.
//
//   npm run test:tokens
import { readFileSync } from "node:fs";
import assert from "node:assert";

const tokens = readFileSync(new URL("../src/styles/tokens.css", import.meta.url), "utf8");
const hosted = readFileSync(new URL("../src/lib/hosted/page_html.ts", import.meta.url), "utf8");
const site = readFileSync(new URL("../src/styles/site.css", import.meta.url), "utf8");

let passed = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); passed++; };

ok(/import\s+TOKENS_CSS\s+from\s+"\.\.\/\.\.\/styles\/tokens\.css\?raw"/.test(hosted),
  "page_html.ts must import tokens.css with ?raw");
ok(hosted.split("${TOKENS_CSS}").length - 1 >= 2,
  "TOKENS_CSS must be interpolated into both the app stylesheet and MINI_PAGE_CSS");
ok(/@import\s+"\.\/tokens\.css"/.test(site), "site.css must import tokens.css");

// No second palette in the hosted file.
for (const forbidden of ["--surface-raised:", "--ink-muted:", "--accent: #"]) {
  ok(!hosted.includes(forbidden), `page_html.ts re-declares ${forbidden}, use tokens.css`);
}

// Both themes exist and carry the same token names.
const names = (block) => new Set([...block.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
const dark = tokens.slice(tokens.indexOf(":root {"), tokens.indexOf('html[data-theme="light"]'));
const light = tokens.slice(tokens.indexOf('html[data-theme="light"]'), tokens.indexOf("/* Film grain"));
for (const n of ["--surface", "--ink", "--ink-muted", "--card", "--solid", "--grid", "--danger"]) {
  ok(names(dark).has(n), `dark theme lacks ${n}`);
  ok(names(light).has(n), `light theme lacks ${n}`);
}

// Embedded in a JS template literal on the server, so none of these may appear.
ok(!tokens.includes("`"), "tokens.css must not contain a backtick");
ok(!tokens.includes("${"), "tokens.css must not contain a template placeholder");
ok(!tokens.includes("\\"), "tokens.css must not contain a backslash");

// One identity: no lime or teal anywhere in the shared styles or the app.
for (const [name, src] of [["tokens.css", tokens], ["site.css", site], ["page_html.ts", hosted]]) {
  ok(!/#c2ff4d|194,\s*255,\s*77|--glow-/i.test(src), `${name} still references the old lime accent`);
}

console.log(`tokens: ${passed} checks passed`);
