import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
export default withMDX({
  // Static export dropped into web/public/docs/, served by the Astro site at
  // /docs. Keeps the marketing site and hosted app on Astro/Cloudflare
  // untouched while the docs get the same Fumadocs UI the tool generates.
  // `next build` and `next dev` share .next by default, so building while a
  // dev server is running corrupts it and every route starts 500ing. Builds
  // set NEXT_DIST_DIR to keep the two apart.
  distDir: process.env.NEXT_DIST_DIR || '.next',
  output: 'export',
  basePath: '/docs',
  images: { unoptimized: true },
  trailingSlash: true,
  // This app has its own lockfile inside a larger repo; without this Next
  // walks up and picks the wrong workspace root.
  outputFileTracingRoot: import.meta.dirname,
});
