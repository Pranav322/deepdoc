# DeepDoc web

One Astro 5 project, three surfaces:

| Surface | Where | Code |
|---|---|---|
| Marketing | `deepdoc.tech` | `src/pages/index.astro`, `src/pages/changelog.astro` |
| Product docs | `deepdoc.tech/docs` | `src/content/docs/**/*.mdx`, `src/pages/docs/` |
| Hosted app | `cloud.deepdoc.tech` | `src/pages/cloud/`, `src/lib/hosted/` |

`src/middleware.ts` rewrites `cloud.deepdoc.tech` requests into `src/pages/cloud/`, so the hosted app keeps clean URLs (`/generate`, `/projects`, `/owner/repo/`).

## Develop

```bash
npm install
npm run dev          # http://localhost:4321
npm run build        # production build into dist/
```

The hosted app branches on hostname, so browse it at `http://cloud.localhost:4321` (Chrome resolves `*.localhost` to loopback). For real D1 and R2 bindings run `npm run build && npx wrangler pages dev dist`.

## Checks

```bash
npm run test:tokens    # one palette across all three surfaces
npm run test:hosted    # parses the hosted app's client JS against a running server
```

## Editing the docs

Add or edit an `.mdx` file under `src/content/docs/`, then list it in `docsSections` in `src/lib/nav.ts`. The build fails if a page is unlisted or a listed page is missing.

## Deploy

Cloudflare Pages, direct upload. From this directory:

```bash
npm run build
npx wrangler pages deploy dist --project-name=deepdoc
```

Design rules, hosted-app constraints and infrastructure notes live in the repository's [`AGENTS.md`](../AGENTS.md) and [`docs/PRODUCTION_INFRA.md`](../docs/PRODUCTION_INFRA.md).
