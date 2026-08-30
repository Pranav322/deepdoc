// This file is written by `deepdoc generate`. Do not edit manually.
// It is regenerated on every `deepdoc generate` / `deepdoc update` run.

import fs from 'node:fs';
import path from 'node:path';

export interface DeepDocConfig {
  project_name: string;
  nav: NavEntry[];
  colors: { primary: string; light: string; dark: string };
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
