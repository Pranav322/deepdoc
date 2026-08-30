import type { ReactNode } from 'react';
import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import { source } from '@/lib/source';
import { SiteHeader, SITE_HEADER_HEIGHT } from '@/components/site-header';

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <>
      <SiteHeader />
      <DocsLayout
        tree={source.pageTree}
        // The site header replaces Fumadocs' own navbar; --fd-nav-height is
        // what the layout offsets its content by.
        nav={{ enabled: false }}
        containerProps={{
          style: { ['--fd-nav-height' as string]: SITE_HEADER_HEIGHT },
        }}
        sidebar={{ defaultOpenLevel: 1 }}
      >
        {children}
      </DocsLayout>
    </>
  );
}
