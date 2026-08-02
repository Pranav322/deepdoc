// The hosted app (src/lib/hosted/page_html.ts) can't import src/styles/global.css
// — it's an HTML string built in a Worker, not an Astro page — so its palette is
// a hand-copy of the marketing tokens. That copy is exactly the kind of thing
// that silently drifts and leaves the two domains looking like different
// products again, which is the problem this was meant to fix.
//
// This asserts the two agree, for both themes. Pure file parsing, no server.
//
//   npm run test:tokens
import { readFileSync } from "node:fs";
import assert from "node:assert";

const css = readFileSync(new URL("../src/styles/global.css", import.meta.url), "utf8");
const hosted = readFileSync(new URL("../src/lib/hosted/page_html.ts", import.meta.url), "utf8");

const norm = (v) => v.trim().toLowerCase().replace(/\s+/g, "").replace(/;$/, "");

/** Values declared inside the first block matching `selector`, at/after `from`. */
function block(src, selector, from = 0) {
  const i = src.indexOf(selector, from);
  assert.ok(i !== -1, `could not find ${selector}`);
  const open = src.indexOf("{", i);
  const close = src.indexOf("}", open);
  const body = src.slice(open + 1, close);
  const out = {};
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = norm(m[2]);
  return out;
}

// Marketing is the source of truth.
const mDark = block(css, "@theme static");
const mLight = block(css, 'html[data-theme="light"]');

// The hosted app drops the --color- prefix (its ~250 lines of CSS predate the
// marketing tokens and reference the short names).
//
// Search from tryPageHtml onwards: MINI_PAGE_CSS (for the two standalone
// pages) declares its own smaller :root earlier in the file, and matching that
// one instead would silently test the wrong block.
const appStart = hosted.indexOf("export function tryPageHtml");
assert.ok(appStart !== -1, "could not locate tryPageHtml");
const hDark = block(hosted, ":root {", appStart);
const hLight = block(hosted, 'html[data-theme="light"] {', appStart);

// MINI_PAGE_CSS defines a deliberate subset — check the ones it does declare.
const miniStart = hosted.indexOf("const MINI_PAGE_CSS");
const miniDark = block(hosted, ":root {", miniStart);
const miniLight = block(hosted, 'html[data-theme="light"] {', miniStart);

// Only the tokens that must match. --accent-ink and --danger are hosted-only
// (there is no button-on-accent or destructive surface on the marketing site),
// and --shadow-lift is presentational.
const SHARED = [
  "ink", "ink-muted", "ink-faint",
  "surface", "surface-raised", "surface-high",
  "line", "line-strong",
  "accent", "accent-dim",
];

let passed = 0;
const fails = [];
for (const [label, marketing, host] of [["dark", mDark, hDark], ["light", mLight, hLight]]) {
  for (const name of SHARED) {
    const want = marketing["--color-" + name];
    const got = host["--" + name];
    if (want === undefined) { fails.push(`${label}: global.css has no --color-${name}`); continue; }
    if (got === undefined) { fails.push(`${label}: page_html.ts has no --${name}`); continue; }
    if (want !== got) {
      fails.push(`${label}: --${name} drifted — global.css "${want}" vs page_html.ts "${got}"`);
    } else passed++;
  }
}

// The two hosted-only tokens still have to exist in both themes, or light mode
// renders unreadable text on the accent button.
for (const [label, host] of [["dark", hDark], ["light", hLight]]) {
  for (const name of ["--accent-ink", "--danger"]) {
    if (host[name] === undefined) fails.push(`${label}: page_html.ts is missing ${name}`);
    else passed++;
  }
}

// The standalone pages share the palette too — whatever subset they declare
// must still agree with marketing, or the 403/stale pages look foreign.
for (const [label, marketing, mini] of [["mini dark", mDark, miniDark], ["mini light", mLight, miniLight]]) {
  for (const name of SHARED) {
    const got = mini["--" + name];
    if (got === undefined) continue; // subset by design
    const want = marketing["--color-" + name];
    if (want !== got) fails.push(`${label}: --${name} drifted — "${want}" vs "${got}"`);
    else passed++;
  }
}

if (fails.length) {
  console.error("Design tokens are out of sync:\n" + fails.map((f) => "  " + f).join("\n"));
  process.exit(1);
}
console.log(`${passed} token values match between global.css and the hosted app`);
