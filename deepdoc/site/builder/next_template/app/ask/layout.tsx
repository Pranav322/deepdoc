import type { ReactNode } from 'react';

// Standalone layout — no Fumadocs sidebar/TOC. The root layout still provides
// <html>, <body>, RootProvider, brand vars, and scripts.
export default function AskLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
