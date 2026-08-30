import type { ReactNode } from 'react';
import type { Metadata } from 'next';
import { RootProvider } from 'fumadocs-ui/provider';
import { getConfig } from '@/lib/config';
import MermaidRunner from '@/app/components/mermaid-runner';
import './globals.css';

export function generateMetadata(): Metadata {
  const cfg = getConfig();
  const favicon = cfg.brand?.favicon;
  return {
    title: { default: cfg.project_name, template: `%s — ${cfg.project_name}` },
    ...(favicon ? { icons: { icon: favicon } } : {}),
  };
}

export default function RootLayout({ children }: { children: ReactNode }) {
  const cfg = getConfig();
  const clientConfig = JSON.stringify({
    chatbot: { backend_url: cfg.chatbot.backend_url ?? '' },
  });

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Theme is composed in Python (see next_builder.theme_css) and read
            from deepdoc.config.json per request, so editing .deepdoc.yaml and
            restarting `deepdoc serve` applies it with no regeneration.
            Precedence is preset -> brand -> explicit token overrides. */}
        <style dangerouslySetInnerHTML={{ __html: cfg.theme.css }} />
        {cfg.theme.google_fonts && (
          <>
            <link rel="preconnect" href="https://fonts.googleapis.com" />
            <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
            <link rel="stylesheet" href={cfg.theme.google_fonts} />
          </>
        )}
        <script dangerouslySetInnerHTML={{ __html: `window.__DD_CONFIG__=${clientConfig};` }} />
      </head>
      <body>
        <RootProvider
          {...(Object.keys(cfg.labels?.ui ?? {}).length
            // `locales` is deliberately omitted: supplying it would render a
            // language switcher, and this is relabelling, not i18n.
            ? { i18n: { locale: 'en', translations: cfg.labels.ui } }
            : {})}
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
