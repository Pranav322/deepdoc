// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";
import sitemap from "@astrojs/sitemap";
import cloudflare from "@astrojs/cloudflare";

// https://astro.build/config
export default defineConfig({
  site: "https://deepdoc.tech",
  // SSR needed for the hosted app (cloud.deepdoc.tech) merged in under
  // src/pages/cloud/ — every marketing page keeps `export const prerender =
  // true` so it stays fully static; only the hosted app is server-rendered.
  output: "server",
  adapter: cloudflare(),
  integrations: [
    sitemap({
      // Keep noindex / placeholder pages out of the sitemap.
      filter: (page) => !page.includes("/changelog"),
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
  build: {
    inlineStylesheets: "auto",
  },
});
