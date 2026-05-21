# DeepDoc — Marketing Site

Public-facing website for DeepDoc at `https://deepdoc.dev`. Built with **Astro 5** and **Tailwind 4**. Ships zero client-side JS by default — static HTML and CSS only, with minimal hydration where needed.

## Stack

| Tool | Version | Role |
|---|---|---|
| Astro | 5.x | Static site generator and component framework |
| Tailwind CSS | 4.x | Utility-first styling via the Vite plugin |
| TypeScript | 5.x | Type checking for `.astro` and `.ts` files |
| pnpm | — | Package manager |

## Local development

```bash
pnpm install
pnpm dev        # dev server at http://localhost:4321 with hot reload
pnpm build      # production build → ./dist/
pnpm preview    # serve the built dist/ locally before deploying
```

## Structure

```
web/
├── astro.config.mjs          # Astro config — site URL, Tailwind Vite plugin
├── tsconfig.json             # TypeScript config
├── public/                   # Static assets served as-is (favicon, og images, …)
└── src/
    ├── layouts/
    │   └── Layout.astro      # Base HTML shell — <head>, global styles, slot
    ├── components/
    │   ├── Header.astro      # Top navigation bar
    │   └── Footer.astro      # Footer links and legal
    └── pages/
        ├── index.astro       # Landing page — hero, features, install snippet
        ├── docs.astro        # Docs landing (placeholder — links to generated site)
        └── changelog.astro   # Changelog page (placeholder)
```

## Adding a new page

1. Create `src/pages/your-page.astro`.
2. Wrap content in `<Layout title="...">`.
3. Link from `Header.astro` if it should appear in the nav.

No routing config needed — Astro maps the file path directly to the URL.

## Styling

Tailwind 4 is wired in as a Vite plugin (`@tailwindcss/vite`). Use utility classes directly in `.astro` files. No `tailwind.config.js` is required for basic usage — Tailwind scans all files automatically.

## Deploy

The `dist/` output is plain static HTML/CSS/JS. It deploys to any static host:

| Platform | How |
|---|---|
| Vercel | Connect the repo, set root to `web/`, build command `pnpm build`, output `dist` |
| Netlify | Same — build command `pnpm build`, publish directory `dist` |
| Cloudflare Pages | Build command `pnpm build`, output `dist` |
| GitHub Pages | Upload `dist/` via `actions/upload-pages-artifact` |

The site URL is set to `https://deepdoc.dev` in `astro.config.mjs` — update this if deploying to a different domain.
