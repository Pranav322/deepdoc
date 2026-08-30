import type { PageTree } from 'fumadocs-core/server';
import { getConfig } from './config';

export interface NavSection {
  type: 'section';
  title: string;
  items: NavItem[];
}

export interface NavPage {
  type?: 'page';
  title: string;
  slug: string;
}

export type NavItem = NavPage | NavSection;

// Build a Fumadocs PageTree from the nav array in deepdoc.config.json
export function buildPageTree(): PageTree.Root {
  const cfg = getConfig();
  const nav = cfg.nav ?? [];

  const children: PageTree.Node[] = [];

  function buildNode(entry: NavItem): PageTree.Node {
    if (entry.type === 'section') {
      return {
        type: 'folder',
        name: entry.title,
        children: (entry.items ?? []).map(buildNode),
        defaultOpen: true,
      };
    }
    return {
      type: 'page',
      name: entry.title,
      url: entry.slug === '/' || entry.slug === 'index' ? '/' : `/${entry.slug}`,
    };
  }

  for (const entry of nav as NavItem[]) children.push(buildNode(entry));

  return { name: cfg.project_name ?? 'Docs', children };
}
