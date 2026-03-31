import './global.css';
import { ChatbotToggle } from '@/components/chatbot-toggle';
import { RootProvider } from 'fumadocs-ui/provider/next';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'codewiki',
  description: 'Auto-generated developer documentation',
  icons: {
    icon: '/favicon.svg',
  },
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-fd-background text-fd-foreground antialiased">
        <RootProvider
          search={{
            options: {
              api: '/search',
              type: 'static',
            },
          }}
        >
          {children}
          <ChatbotToggle />
        </RootProvider>
      </body>
    </html>
  );
}
