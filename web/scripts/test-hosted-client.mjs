// Behaviour tests for the hosted app's client JS (src/lib/hosted/page_html.ts).
//
// That JS lives inside a template string, so neither tsc nor the Astro build
// ever parses it — a syntax error or a regressed failure path ships silently.
// This pulls the REAL rendered script off a running server and exercises
// poll()'s failure paths against a stubbed DOM + fetch.
//
//   npm run build && npx wrangler pages dev dist --port 8788
//   npm run test:hosted
import assert from "node:assert";

// Point at a running server: `npm run build && npx wrangler pages dev dist --port 8788`
const BASE = process.env.HOSTED_BASE || "http://localhost:8788";
const res = await fetch(BASE + "/cloud/").catch(() => null);
if (!res || !res.ok) {
  console.error(`Could not reach ${BASE}/cloud/ — start the server first:\n` +
    "  npm run build && npx wrangler pages dev dist --port 8788");
  process.exit(1);
}
const html = await res.text();
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/);
if (!scriptMatch) { console.error("Could not find the client script in the rendered page."); process.exit(1); }
const raw = scriptMatch[1];
// Strip the boot call so evaluating the script doesn't kick off the whole app
// and consume our stubbed fetch. Matches both `main();` and
// `main().catch(renderFatal);`.
const src = raw.replace(/\bmain\(\)(?:\.catch\([^)]*\))?;\s*$/, "");
if (/\bmain\(\)/.test(src.slice(-400))) {
  console.error("Could not strip the boot call — the harness would run main(). Update the regex.");
  process.exit(1);
}

function makeEl(id) {
  return {
    id, innerHTML: "", textContent: "", hidden: false, dataset: {}, className: "",
    style: {}, classList: { add() {}, remove() {}, toggle() {} },
    querySelectorAll: () => [], querySelector: () => null, appendChild() {},
  };
}

function harness({ fetchImpl, present = ["stage-list", "result-slot", "gen-elapsed", "content"], cards = [], store = {} }) {
  const els = new Map(present.map((id) => [id, makeEl(id)]));
  const cardEls = cards.map((name) => ({ ...makeEl("card"), hidden: false, dataset: { name } }));
  const scheduled = [];
  const ctx = {
    document: {
      getElementById: (id) => els.get(id) || null,
      createElement: (t) => makeEl(t),
      addEventListener() {}, removeEventListener() {},
      querySelectorAll: (sel) => (String(sel).includes(".card[data-name]") ? cardEls : []),
      querySelector: () => null,
    },
    window: { location: { pathname: "/", href: "" }, addEventListener() {}, matchMedia: () => ({ matches: false }) },
    location: { pathname: "/", href: "" },
    history: { pushState() {}, replaceState() {} },
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem(k, v) { store[k] = String(v); },
      removeItem(k) { delete store[k]; },
    },
    fetch: fetchImpl,
    setTimeout: (fn, ms) => { scheduled.push({ fn, ms }); return scheduled.length; },
    clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    console,
  };
  const fn = new Function(...Object.keys(ctx), src +
    "\n;return { poll, escapeHtml, pollDelayMs, selectRepoByName, state, route," +
    " onGallerySearch, parseGithubUrlClient, startFromGallery, consumePendingRepo," +
    " getStartInFlight: () => startInFlight, setStartInFlight: (v) => { startInFlight = v; } };");
  const api = fn(...Object.values(ctx));
  return { api, els, scheduled, cardEls, store };
}

let passed = 0;
const check = (name, cond) => { assert.ok(cond, "FAILED: " + name); console.log("  pass:", name); passed++; };

// ── 1. Expired session (401) — the headline bug ─────────────────────────
{
  let calls = 0;
  const { api, els, scheduled } = harness({
    fetchImpl: async () => { calls++; return { ok: false, status: 401, json: async () => ({ error: "not authenticated" }) }; },
  });
  await api.poll("job1", "acme", "widgets");
  check("401 fetches exactly once (no infinite loop)", calls === 1);
  check("401 schedules NO further poll", scheduled.length === 0);
  check("401 tells the user the session expired", /session expired/i.test(els.get("result-slot").innerHTML));
  check("401 says the build is still running", /still running/i.test(els.get("result-slot").innerHTML));
  check("401 offers a retry", /resumePoll/.test(els.get("result-slot").innerHTML));
}

// ── 2. Transient network failure — backs off, then gives up ─────────────
{
  let calls = 0;
  const { api, els, scheduled } = harness({ fetchImpl: async () => { calls++; throw new Error("network down"); } });
  // Drive the retry chain synchronously via the captured setTimeout callbacks.
  await api.poll("job2", "acme", "widgets");
  let guard = 0;
  while (scheduled.length && guard++ < 10) {
    const next = scheduled.shift();
    await next.fn();
  }
  check("transient failure retries then stops", calls === 5);
  check("gives up with a 'lost contact' message", /lost contact/i.test(els.get("result-slot").innerHTML));
  check("no poll left scheduled after giving up", scheduled.length === 0);
}

// ── 3. Backoff actually grows ───────────────────────────────────────────
{
  const delays = [];
  let calls = 0;
  const { api, scheduled } = harness({ fetchImpl: async () => { calls++; throw new Error("down"); } });
  await api.poll("job3", "a", "b");
  let guard = 0;
  while (scheduled.length && guard++ < 10) {
    const next = scheduled.shift();
    delays.push(next.ms);
    await next.fn();
  }
  // Non-decreasing, not strictly increasing: it plateaus once the cap engages.
  check("backoff never shrinks", delays.length >= 3 && delays.every((d, i) => i === 0 || d >= delays[i - 1]));
  check("backoff actually grows", delays[delays.length - 1] > delays[0]);
  check("backoff caps at 15s", Math.max(...delays) <= 15000);
  check("backoff starts above the 2s happy-path interval", delays[0] > 2000);
}

// ── 4. Happy path still polls ───────────────────────────────────────────
{
  const { api, scheduled } = harness({
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ status: "building" }) }),
  });
  await api.poll("job4", "a", "b");
  check("in-progress status reschedules", scheduled.length === 1 && scheduled[0].ms === 2000);
}

// ── 5. Malformed payload is treated as a failure, not as a stage ────────
{
  const { api, scheduled } = harness({
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ nonsense: true }) }),
  });
  await api.poll("job5", "a", "b");
  check("malformed payload retries rather than rendering a bogus stage", scheduled.length === 1 && scheduled[0].ms > 2000);
}

// ── 6. Navigating away stops the loop ───────────────────────────────────
{
  let calls = 0;
  const { api, scheduled } = harness({
    fetchImpl: async () => { calls++; return { ok: true, status: 200, json: async () => ({ status: "building" }) }; },
    present: ["content"], // no stage-list => user left the progress screen
  });
  await api.poll("job6", "a", "b");
  check("stops cleanly when the progress screen is gone", calls === 0 && scheduled.length === 0);
}

// ── 7. escapeHtml closes the injection hole ─────────────────────────────
{
  const { api } = harness({ fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({}) }) });
  const out = api.escapeHtml('<img src=x onerror=alert(1)>');
  check("escapeHtml neutralises tags", !out.includes("<") && out.includes("&lt;"));
  check("escapeHtml neutralises quotes", api.escapeHtml(`a"b'c`) === "a&quot;b&#39;c");
}

// ── 8. The submit guard must not outlive the submit ─────────────────────
// Regression: startJob() sets startInFlight and only cleared it on the two
// failure paths, so after a successful POST the flag stayed true for the life
// of the page — making the Retry button on a failed build, and the Generate
// button after "Back to generate", silently inert.
{
  const { api, els } = harness({
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ status: "failed", error: "boom" }) }),
  });
  api.setStartInFlight(true);
  await api.poll("job7", "a", "b");
  check("a failed build releases the submit guard so Retry works", api.getStartInFlight() === false);
  check("a failed build still renders the Retry button", /retryJob/.test(els.get("result-slot").innerHTML));
  check("backend error text is escaped, not injected", !/<script/i.test(els.get("result-slot").innerHTML));
}
{
  const { api } = harness({ fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({}) }) });
  api.setStartInFlight(true);
  api.state.me = { authenticated: true };
  api.state.projects = [];
  try { api.route(); } catch { /* rendering needs DOM we don't stub; the reset is what matters */ }
  check("navigating releases the submit guard", api.getStartInFlight() === false);
}

// ── 8. The gallery's one field: filter + "paste a link" detection ───────
{
  const { api, els, cardEls } = harness({
    fetchImpl: async () => ({ ok: true, json: async () => ({}) }),
    present: ["content", "ask-slot"],
    cards: ["microsoft/vscode visual studio code typescript", "karpathy/nanochat the best chatgpt python"],
  });

  api.onGallerySearch("nanochat");
  check("filter hides cards that do not match", cardEls[0].hidden === true);
  check("filter keeps cards that match", cardEls[1].hidden === false);

  api.onGallerySearch("");
  check("an empty query restores every card", cardEls.every((c) => c.hidden === false));

  // Matching on description text, not just the name.
  api.onGallerySearch("typescript");
  check("filter also matches the description", cardEls[0].hidden === false && cardEls[1].hidden === true);

  api.onGallerySearch("zzzz-no-such-repo");
  check("a query matching nothing explains the next step", /paste a github link/i.test(els.get("ask-slot").innerHTML));

  api.onGallerySearch("https://github.com/acme/widgets");
  const hit = els.get("ask-slot").innerHTML;
  check("a pasted GitHub link offers to generate it", /startFromGallery/.test(hit) && /acme\/widgets/.test(hit));
  check("a pasted link does not leave a stale no-match note", !/matches that/i.test(hit));

  // The raw value lands inside a single-quoted onclick attribute.
  api.onGallerySearch("https://github.com/a/b'+alert(1)+'");
  check("a quote in the pasted URL cannot break out of the onclick",
    !/'\+alert\(1\)\+'/.test(els.get("ask-slot").innerHTML));
}

// ── 9. A link pasted before sign-in survives the OAuth round trip ───────
{
  const { api, els, store } = harness({
    fetchImpl: async () => ({ ok: true, json: async () => ({}) }),
    present: ["content", "ask-slot", "modal-slot", "paste-url", "paste-confirm-slot", "confirm-slot", "repo-list"],
  });
  api.startFromGallery("https://github.com/acme/widgets");
  check("the pasted repo is stored before the OAuth redirect", store.dd_pending_repo === "https://github.com/acme/widgets");

  api.state.projects = [];
  api.consumePendingRepo();
  check("after sign-in the paste field is prefilled", els.get("paste-url").value === "https://github.com/acme/widgets");
  check("the pending repo is consumed exactly once", store.dd_pending_repo === undefined);

  els.get("paste-url").value = "";
  api.consumePendingRepo();
  check("a second visit does not resurrect it", els.get("paste-url").value === "");
}

console.log(`\n${passed} checks passed`);
