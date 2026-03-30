import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import { layoutOptions } from '@/lib/layout-options';
import { pageTree } from '@/lib/page-tree.generated';
import type { ReactNode } from 'react';

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <DocsLayout tree={pageTree} {...layoutOptions}>
      {children}
    </DocsLayout>
  );
}
