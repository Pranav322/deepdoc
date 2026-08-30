import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
export default withMDX({
  // Static export dropped into web/public/docs/, served by the Astro site at
  // /docs. Keeps the marketing site and hosted app on Astro/Cloudflare
  // untouched while the docs get the same Fumadocs UI the tool generates.
  output: 'export',
  basePath: '/docs',
  images: { unoptimized: true },
  trailingSlash: true,
});
