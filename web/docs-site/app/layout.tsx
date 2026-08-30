import type { ReactNode } from 'react';
import type { Metadata } from 'next';
import { RootProvider } from 'fumadocs-ui/provider';
import './global.css';

export const metadata: Metadata = {
  title: { default: 'DeepDoc Docs', template: '%s — DeepDoc' },
  description:
    'Generate a beautiful, themeable documentation site from any codebase — one command, your branding.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <RootProvider
          search={{
            // The index is a static asset (see app/api/search/route.ts), so
            // searching happens in the browser. Without this the client calls
            // a dynamic endpoint that cannot exist in an exported site.
            options: { type: 'static' },
          }}
        >
          {children}
        </RootProvider>
      </body>
    </html>
  );
}
