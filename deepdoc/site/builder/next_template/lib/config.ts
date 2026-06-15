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

let _cache: DeepDocConfig | null = null;

export function getConfig(): DeepDocConfig {
  if (_cache) return _cache;
  const cfgPath = path.join(process.cwd(), 'deepdoc.config.json');
  _cache = JSON.parse(fs.readFileSync(cfgPath, 'utf-8')) as DeepDocConfig;
  return _cache;
}
