import type { PageTree } from 'fumadocs-core/server';
import { getConfig } from './config';

export interface NavSection {
  title: string;
  items: NavItem[];
}

export interface NavItem {
  title: string;
  slug: string;
}

// Build a Fumadocs PageTree from the nav array in deepdoc.config.json
export function buildPageTree(): PageTree.Root {
  const cfg = getConfig();
  const nav = cfg.nav ?? [];

  const children: PageTree.Node[] = [];

  for (const entry of nav) {
    if (entry.type === 'page') {
      children.push({
        type: 'page',
        name: entry.title,
        url: entry.slug === 'index' ? '/' : `/${entry.slug}`,
      });
    } else if (entry.type === 'section') {
      const sectionItems: PageTree.Node[] = (entry.items ?? []).map(
        (item: { title: string; slug: string }) => ({
          type: 'page' as const,
          name: item.title,
          url: `/${item.slug}`,
        }),
      );
      children.push({
        type: 'folder',
        name: entry.title,
        children: sectionItems,
        defaultOpen: true,
      });
    }
  }

  return { $ref: {}, name: cfg.project_name ?? 'Docs', children };
}
