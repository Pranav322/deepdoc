# Hosted UI spec — cloud.deepdoc.tech

This documents the **current** `cloud.deepdoc.tech` UI as of 2026-07-25 —
IA/visual content unchanged since the 2026-07-24 revamp described below, but
**as of 2026-07-25 the code moved**: `web/hosted/` (a standalone Cloudflare
Worker) is retired, merged into the same Astro project as the marketing site
(`web/`). Server routes now live under `web/src/pages/cloud/` (one thin
endpoint file per route — `index.ts`, `generate.ts`, `projects/index.ts`,
`projects/[owner]/[repo].ts`, the `api/*` endpoints, and the
`[owner]/[repo]/[...path].ts` site-proxy catch-all); the markup/CSS/client-JS
payload (`tryPageHtml()`, `privateSitePage()`, `stalePageHtml()`) was ported
verbatim into `web/src/lib/hosted/page_html.ts`. `web/src/middleware.ts` is
what routes `cloud.deepdoc.tech` requests into that `cloud/` namespace while
keeping marketing (`deepdoc.tech`) untouched — see `AGENTS.md`'s
"Hosted-generation" section for the full mechanics. Purpose of this file: a
checklist so a future change doesn't silently drop a flow, a business rule,
or an edge case — none of that changed in the framework move.

Everything here is one server-rendered SPA (`tryPageHtml()`, now in
`page_html.ts`) plus two standalone one-off pages (`privateSitePage`,
`stalePageHtml`; the served static doc sites themselves aren't part of this
app).

---

## 1. Pages / views inventory

| View | Route(s) that serve it | Auth required | Purpose |
|---|---|---|---|
| **Sign-in prompt** | `/` (when `/api/me` says unauthenticated) | no | **Not a landing page** — deepdoc.tech's own marketing landing already sells the product and its "Try it free" CTA sends people straight to `cloud.deepdoc.tech`; this is just the gate: a short explainer (3 bullets on the GitHub repo-read grant) + "Continue with GitHub". No hero, no product mockup, no second pitch. |
| **Generate** | `/generate` (also the default at `/` once authenticated, if the user has no saved projects) | yes | Repo picker + paste-URL + visibility + confirm. Minimal, no dashboard framing, no back-link. |
| **Projects list** | `/projects` (also the default at `/` once authenticated, if the user has ≥1 saved project) | yes | Pure index of saved projects. Click-through rows only — no buttons in the row. |
| **Project detail** | `/projects/:owner/:repo` | yes | **The only place per-project actions live**: "Visit site ↗", Visibility toggle, Danger Zone (Delete, with an inline "Confirm delete?" step — no native `confirm()`). |
| **Profile dropdown** | client-side overlay off the avatar chip, any authenticated view | yes | Identity + quota line, "Projects (N) ›" link, "Generate new" link, Log out. **No project rows here** — deliberately kept out, lives only on `/projects`. |
| **Generating / progress** | any `/{owner}/{repo}/` while status ≠ done/failed (client also lands here right after POST `/api/generate`) | yes | Collapsible 3-stage list (cloning/generating/building) + elapsed-time counter. No percentage/estimate — rejected explicitly since the backend has no real completion signal within a stage. |
| **Generated site (proxied)** | `/{owner}/{repo}/*` once status is `done` | depends on visibility | The actual static docs site, served byte-for-byte from R2 |
| **Private-site block page** | `/{owner}/{repo}/*` when private and viewer isn't the owner | n/a (this IS the response) | Explains why they can't see it; different copy signed-in vs anon |
| **Stale-site page** | `/{owner}/{repo}/*` when status says done/failed but R2 has nothing | n/a | Honest "the files are gone, regenerate" message, CTA → `/generate` |
| **App shell (mid-generation direct hit)** | `/{owner}/{repo}/*` when status is still queued/generating/building and someone requests the URL directly (not via client nav) | n/a | Re-serves the SPA shell so client JS resumes polling |

**Default-route rule**: `/` never renders content of its own — the client
resolves it to `/projects` if the authed user has any saved project, else
`/generate`, and rewrites the URL to match (`history.replaceState`). The
OAuth callback and stale `/try`/`/account`/`/new` bookmarks all redirect to
`/` and let this one rule decide, rather than hardcoding a page server-side.

**Retired routes** — `/try`, `/account`, `/new` no longer exist as pages;
hitting any of them 302-redirects to `/` (stale-bookmark handling, not a 404).

The app bar mirrors `deepdoc.tech`'s own `Header.astro`/`Logo.astro` recipe
(52px sticky bar, blurred background, the same "depth D" brand mark —
duplicated as inline SVG in `try_page.ts` since the Worker can't import an
Astro component) so both domains read as one product. It's shown in every
view including the unauthenticated sign-in prompt (just without the account
chip).

---

## 2. Client-side SPA states (all inside `tryPageHtml()`'s `<script>`)

The whole logged-in experience is one JS state machine keyed off
`window.location.pathname` via `pushState`, no framework, no router library.

- `main()` — boots on load: fetch `/api/me`; if authed, fetch `/api/projects`,
  then check if the current path is an in-flight `/{owner}/{repo}` project and
  resume polling; otherwise call `route()`.
- `route()` — dispatches on pathname: `/projects/:owner/:repo` (regex) →
  `renderProjectDetail()`; `/projects` → `renderProjects()`; `/generate` →
  `renderGenerate()`; anything else (in practice just `/`) → the default-route
  rule (`renderProjects()` if `state.projects.length`, else `renderGenerate()`),
  rewriting the URL via `history.replaceState` to match what actually rendered.
- `nav(e, path)` — intercepts link/row clicks, closes the profile dropdown if
  open, `pushState` + re-route, no full reload.
- `popstate` listener — back/forward button support.
- `renderAppBar()` — brand link (→ `/`, re-runs the default-route rule) +
  avatar/login chip (toggles the profile dropdown, does not navigate).
- `renderDropdown()` / `toggleDropdown()` / `closeDropdown()` — the profile
  popover: identity, quota line, "Projects (N) ›", "Generate new", Log out.
  Closes on outside-click or Escape (listeners attached only while open).
- `brandMarkHtml()` — the inline-SVG "depth D" mark + "eepDoc" wordmark +
  small "cloud" tag, shared by `renderAppBar()` and `renderLoggedOut()` so the
  brand renders identically authed or not.
- `renderLoggedOut()` — the sign-in prompt (see table above): 3-bullet
  explainer + "Continue with GitHub" (`/auth/github` redirect). No modal, no
  hero — this is the entire unauthenticated experience.
- `renderGenerate()` — the post-login home:
  - "at quota" state: replaces the whole form with a message pointing at
    `/projects` to free a slot (no separate gating on the dropdown link).
  - Repo search input (`filterRepos`, client-side substring filter over
    `state.repos`) + repo list (`renderRepoList`, from `/api/repos`) — click a
    row → `selectRepo` → confirm panel with visibility picker + Generate.
  - "or paste a public repo URL" divider + paste input
    (`generateFromPaste`) — any public GitHub URL, doesn't require it be in
    the user's own repo list.
  - Error slot — inline red error box (409 ownership conflict, quota errors,
    generic queue failure, etc.).
- `visChoiceHtml()` / `pickVis()` — the reusable "🔒 Private / 🌐 Public" pill
  pair + hint line, used on both the repo-confirm panel and the paste flow,
  and again (read/write) on the project-detail page. Defaults to **private**
  every time `renderGenerate()` mounts.
- `renderProjects()` — click-through list; empty state points at `/generate`.
  Each row: repo name, a read-only visibility badge, status (text + dot), a
  trailing chevron. No buttons in the row — the whole row navigates to
  `/projects/:owner/:repo`.
- `renderProjectDetail(owner, repo)` — resolves the project from the already
  fetched `/api/projects` list (no separate single-project endpoint). Renders
  "Visit site ↗" (disabled unless `status === 'done'`), the Visibility
  section (`setProjectVisibility`, POSTs then re-renders), and the Danger
  Zone (`confirmDeleteStep` flips the button to an inline "Confirm delete?" +
  Cancel before `deleteProject` actually calls the DELETE endpoint and
  navigates back to `/projects`).
- `renderGenerating(info)` / `renderStageList(currentStage)` /
  `toggleStage(s)` — the 3 fixed stages, `cloning → generating → building`,
  each a collapsible row (click to expand/collapse; the active stage is
  pre-expanded) showing a short static "what's happening" bullet list per
  stage (`STAGE_DETAIL`). An elapsed-time counter (`updateElapsed`,
  `setInterval`) runs alongside — no percentage anywhere.
- `poll(jobId, owner, repo)` — hits `/api/status/{jobId}` every 2s;
  - `done` → stop the elapsed timer, real `window.location.href` navigation
    (not client routing) to `/{owner}/{repo}/` after 700ms, since it now needs
    to load the generated site's own JS bundle.
  - `failed` → error box with `data.error` text, Retry button (`retryJob`,
    re-POSTs `/api/generate` with the same repo info) + "Back to generate".
  - otherwise → re-render the stage list at the new stage, poll again in 2s.
- `backToGenerate()` — pushState to `/generate`, refresh + re-render.
- Logout (`logout()`) — `POST /api/logout` then a hard navigation to `/`.

---

## 3. Business rules the UI must keep enforcing / reflecting

1. **Visibility default is private**, every single generate action (repo pick
   or paste) starts on the private pill selected; user must explicitly choose
   public.
2. **Visibility is per-canonical-site, not per-user-view.** Toggling it (on
   the project-detail page) calls `POST /api/projects/:owner/:repo/visibility`,
   which updates both the caller's own `projects` row and — only if they are
   the owner — the single `owner_repo_jobs` row that actually governs serving.
3. **One canonical site per repo — first generator owns it.** A second user
   trying to generate a repo someone else already generated gets a `409` with
   message "Someone else already generated docs for this repo. One site per
   repo." — must surface this string (or an equivalent) in the error slot, not
   swallow it.
4. **Re-clicking generate on your own in-flight job** doesn't start a
   duplicate — the API returns `202` with the existing job's status, and the
   UI should resume that job's progress view rather than erroring.
5. **Quotas**: `MAX_SAVED_PROJECTS = 2`, `MAX_STARTS_PER_DAY = 2` per user,
   both **unenforced for logins in `UNLIMITED_LOGINS`** (currently just
   `pranav322`) — the quota line in the dropdown and the "at quota" gate on
   `/generate` both key off this.
6. **Private-site enforcement is a real trust boundary, not cosmetic** — the
   private-site block page and the different copy for signed-in-but-not-owner
   vs anonymous-visitor must remain distinct (re-auth is useless for the
   former, useful for the latter).
7. **Stale-site case is called out honestly**, not silently redirected — "the
   files are gone, regenerating fixes it," with a Regenerate CTA → `/generate`.
8. **Mid-generation direct hit** (someone opens `/{owner}/{repo}/` mid-run,
   e.g. refresh or a shared link before it's done) must resume the *live*
   progress view, not show a blank/broken page — this is why the app shell is
   re-served for non-terminal statuses.
9. **The URL bar moves to `/{owner}/{repo}/` the moment generation starts**
   (not after it finishes) — so the progress view, and the eventual finished
   site, live at the same shareable URL throughout.
10. **Stage labels**: `cloning → generating → building` is the fixed 3-stage
    vocabulary the backend emits and the UI must map 1:1 (`STAGE_LABEL` /
    `STAGES` in the JS) — restyling is fine, but the stage set/order is
    contract with the backend (`hosted-runner/pipeline.py`'s `write_status`
    calls), not just UI.
11. **"Visit site" only enabled once `status === 'done'`** — never link to a
    repo still generating.
12. **Log out** must delete the D1 session row (`POST /api/logout`) and expire
    the cookie, and land the browser back at `/`.
13. **Delete requires two clicks** (Delete → "Confirm delete?" inline, not a
    native `confirm()` popup) — a UX rule added in the revamp, don't regress
    to a single-click destructive action.
14. **Project management lives only on `/projects` and `/projects/:owner/:repo`**
    — never inline on `/generate`, never inside the profile dropdown. This was
    an explicit, repeated user correction during the revamp (first pulled off
    the dashboard, then pulled back out of the dropdown too) — don't
    re-introduce project rows/actions anywhere else.

---

## 4. API contract the frontend consumes (must not change without a backend PR)

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/me` | GET | optional | `{authenticated: bool, login?, avatarUrl?}` |
| `/auth/github` | GET (redirect) | no | starts OAuth |
| `/api/auth/callback/github` | GET (redirect) | no | OAuth callback, sets cookie, redirects to `/` (client resolves the default view) |
| `/api/logout` | POST | yes | clears session |
| `/api/repos` | GET | yes | user's own GitHub repos (owner-affiliation only), simplified shape |
| `/api/generate` | POST | yes | body: `{owner,repo}` or `{repo_url}`, `+description?,language?,avatarUrl?,visibility?}`; `202` on enqueue/resume, `400`/`409`/`429`/`502` on rejection, all with `{error}` |
| `/api/status/:jobId` | GET | yes | `{status, error?}` — raw passthrough of R2 `status.json` |
| `/api/projects` | GET | yes | `{projects: [...], quota: {unlimited, savedProjects, maxSavedProjects, startsInWindow, maxStartsPerDay}}` — also the data source for the project-detail page (no separate single-project endpoint) |
| `/api/projects/:owner/:repo` | DELETE | yes | removes the caller's saved-project row only |
| `/api/projects/:owner/:repo/visibility` | POST | yes | body `{visibility: 'public'\|'private'}` |
| `/{owner}/{repo}/*` | GET | conditional | proxies the generated static site from R2, or one of the special pages above |

These shapes are unchanged by the revamp — only which page calls them and
when. They remain load-bearing for the existing `hosted-runner` and D1
schema; changing them is a backend task, not a frontend one.

---

## 5. Current visual identity

**Both themes**, driven by the shared `dd_theme` cookie on `.deepdoc.tech` and read
server-side so the first byte is already correct (the earlier dark-only hardcoding is
gone). The palette is a hand-copy of the marketing tokens, enforced by
`npm run test:tokens`.

Reworked 2026-08-03 into a real design system (see AGENTS.md, "The hosted app's design
system", for the full rule list and the traps). The four rules that define the look:

1. **The accent is a state colour, not a fill.** `#C2FF4D` marks selection, focus,
   live/ready status and the brand mark. Primary buttons are ink-filled (near-white on
   dark, near-black on light) via `--solid`/`--solid-ink`. Restraint here is what makes
   the app read as expensive rather than as a neon startup dashboard.
2. **DM Sans carries everything; JetBrains Mono is for code only** (a pasted repo URL,
   inline `code`). Repo names and page titles are sans. Mono-as-UI-text was the main
   reason the signed-in screens read as a terminal toy.
3. **One page width** (`--w-page`, 736px for `/generate` + detail + progress, 1152px for
   the two grids) shared by the app bar and the content column, so the brand mark sits
   above the page title. Each render function sets it; `route()` does not.
4. **One button shape, one type ramp, one segmented control.** No second vocabulary for
   the same job on a different screen.

Emoji (the old `🔒 Private` / `🌐 Public` pills), uppercase letterspaced mono
micro-labels, and the bordered "danger zone" panel were all removed in that pass. The
visibility choice is a segmented control; delete is a quiet text button that still
requires the two-step confirm (rule 13 below).

**Layout (2026-08-03, second pass — modelled on DeepWiki):** the public gallery and
`/projects` are the same `.card-grid`, each led by one accent-gradient `.card-new` that is
the primary CTA (it replaced `/projects`'s header "Generate new" button — don't re-add
one). Gallery cards carry a real screenshot of the generated site; **project cards
deliberately carry none**, because on your own list the name and build state are what you
scan for. The gallery gained a centered "Which repository would you like documented?" ask
plus one field that both filters the examples and recognises a pasted GitHub link, handing
it to `/generate` through `localStorage.dd_pending_repo` so it survives the OAuth round
trip. The rotating "border beam" and the mousemove 3D card tilt were removed: the grid is
calm and flat, and both fought it.

---

## 6. Known interaction/edge-case gaps (still open, not regressions from this revamp)

- No visible feedback for *how long* generation might take beyond an elapsed
  counter (no ETA) — a real repo takes minutes.
- No confirmation before Retry re-spends a quota slot.
- Repo list has no pagination (GitHub API call is capped at
  `per_page=100`, `affiliation=owner` only — forks/org repos the user has
  access to but doesn't own aren't listed at all, only pasteable by URL).
- No visible rate-limit *countdown* — the 429 error is just a string, no "try
  again in Xh" computed client-side.

Resolved by this revamp (kept here so the history isn't lost): delete now
requires an inline confirm step (was single-click); the generating page now
shows real per-stage detail instead of only a spinner/dots with no context.
