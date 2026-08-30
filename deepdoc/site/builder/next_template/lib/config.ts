// This file is written by `deepdoc generate`. Do not edit manually.
// It is regenerated on every `deepdoc generate` / `deepdoc update` run.

import fs from 'node:fs';
import path from 'node:path';

export interface DeepDocConfig {
  project_name: string;
  nav: NavEntry[];
  colors: { primary: string; light: string; dark: string };
  theme: {
    preset: string;
    /** Precomposed CSS injected into <head>; see next_builder.theme_css. */
    css: string;
    /** Google Fonts URL, or "" when no fonts are configured (the default). */
    google_fonts: string;
    code_theme: { light: string; dark: string };
  };
  chrome: {
    sidebar: boolean;
    sidebar_default_open_level: number;
    sidebar_collapsible: boolean;
    toc: boolean;
    toc_style: 'clerk' | 'normal';
    toc_depth: number[];
    breadcrumb: boolean;
    page_footer: boolean;
    edit_link: boolean;
    last_update: boolean;
    theme_switch: boolean;
    search: boolean;
    generated_meta: boolean;
    links: { text: string; url: string }[];
  };
  brand: { logo?: string; logo_dark?: string; favicon?: string };
  repo: { url: string; owner: string; name: string; branch: string; path_prefix: string };
  labels: { ui: Record<string, string>; callouts: Record<string, string> };
  chatbot: { enabled: boolean; backend_url: string };
  generated_at: string;
  commit_sha: string;
}

type NavEntry =
  | { type: 'page'; title: string; slug: string }
  | { type: 'section'; title: string; items: { title: string; slug: string }[] };

export function getConfig(): DeepDocConfig {
  // Read on every call rather than caching at module scope. The file is not an
  // import, so nothing invalidates a module-level cache — under `next dev` the
  // first read would be pinned for the life of the server process and config
  // changes would never appear without a full restart.
  const cfgPath = path.join(process.cwd(), 'deepdoc.config.json');
  return JSON.parse(fs.readFileSync(cfgPath, 'utf-8')) as DeepDocConfig;
}
