// @ts-check
import { defineConfig } from "astro/config";
import mdx from "@astrojs/mdx";
import sitemap from "@astrojs/sitemap";
import cloudflare from "@astrojs/cloudflare";

// One Astro project serves three surfaces:
//   deepdoc.tech            marketing (src/pages/index.astro)
//   deepdoc.tech/docs       product docs (src/content/docs + src/pages/docs)
//   cloud.deepdoc.tech      hosted app (src/pages/cloud, via src/middleware.ts)
// Everything except the hosted app is prerendered; only src/pages/cloud and the
// marketing index (which shares "/" with the hosted shell) render per request.
export default defineConfig({
  site: "https://deepdoc.tech",
  output: "server",
  adapter: cloudflare(),
  integrations: [
    mdx(),
    sitemap({
      // Keep the hosted app out, but not the /docs/cloud page.
      filter: (page) => !new URL(page).pathname.startsWith("/cloud"),
    }),
  ],
  markdown: {
    // Colours come from CSS variables in docs.css, so code blocks follow the
    // site's light/dark switch without a second render.
    shikiConfig: {
      themes: { light: "min-light", dark: "min-dark" },
      defaultColor: false,
      wrap: false,
      transformers: [
        {
          // ```yaml title=".deepdoc.yaml" -> a filename bar above the block.
          pre(node) {
            const raw = this.options.meta?.__raw ?? "";
            const m = raw.match(/title="([^"]+)"/);
            if (m) node.properties["data-title"] = m[1];
          },
        },
      ],
    },
  },
  build: {
    inlineStylesheets: "auto",
  },
});
