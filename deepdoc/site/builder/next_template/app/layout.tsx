import type { ReactNode } from 'react';
import type { Metadata } from 'next';
import { RootProvider } from 'fumadocs-ui/provider';
import { getConfig } from '@/lib/config';
import MermaidRunner from '@/app/components/mermaid-runner';
import './globals.css';

export function generateMetadata(): Metadata {
  const cfg = getConfig();
  return { title: { default: cfg.project_name, template: `%s — ${cfg.project_name}` } };
}

export default function RootLayout({ children }: { children: ReactNode }) {
  const cfg = getConfig();
  const clientConfig = JSON.stringify({
    chatbot: { backend_url: cfg.chatbot.backend_url ?? '' },
  });

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <style dangerouslySetInnerHTML={{
          __html: `:root{--brand:${cfg.colors.primary || '#eb3e25'};--brand-light:${cfg.colors.light || '#ef624e'};--brand-dark:${cfg.colors.dark || '#c1331f'};}`,
        }} />
        <script dangerouslySetInnerHTML={{ __html: `window.__DD_CONFIG__=${clientConfig};` }} />
      </head>
      <body>
        <RootProvider
          search={{
            // The index is a static asset (see app/api/search/route.ts), so
            // searching happens in the browser. Without this the client would
            // call a dynamic endpoint that cannot exist in an exported site.
            options: { type: 'static' },
          }}
        >
          <MermaidRunner />
          {children}
        </RootProvider>
      </body>
    </html>
  );
}
