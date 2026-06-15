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
        <RootProvider>
          <MermaidRunner />
          {children}
        </RootProvider>
      </body>
    </html>
  );
}
