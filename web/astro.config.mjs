// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";
import sitemap from "@astrojs/sitemap";

// https://astro.build/config
export default defineConfig({
  site: "https://deepdoc.tech",
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
