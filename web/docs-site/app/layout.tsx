import type { ReactNode } from 'react';
import type { Metadata } from 'next';
import { RootProvider } from 'fumadocs-ui/provider';
import './global.css';

const SITE = 'https://www.deepdoc.tech';

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: { default: 'DeepDoc Documentation', template: '%s — DeepDoc' },
  description:
    'Generate a beautiful, themeable documentation site from any codebase — one command, your branding, no hand-writing.',
  applicationName: 'DeepDoc',
  icons: { icon: '/favicon.svg' },
  openGraph: {
    type: 'website',
    siteName: 'DeepDoc',
    url: `${SITE}/docs`,
    title: 'DeepDoc Documentation',
    description:
      'Generate a beautiful, themeable documentation site from any codebase — one command, your branding.',
    images: ['/og.jpg'],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'DeepDoc Documentation',
    description: 'Generate a documentation site from any codebase — one command, your branding.',
    images: ['/og.jpg'],
  },
  robots: { index: true, follow: true },
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
