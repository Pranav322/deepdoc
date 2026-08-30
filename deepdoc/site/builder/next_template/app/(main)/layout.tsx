import type { ReactNode } from 'react';
import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import { buildPageTree } from '@/lib/nav';
import { getConfig } from '@/lib/config';
import { ChatbotWidget } from '@/components/chatbot';

export default function DocsRootLayout({ children }: { children: ReactNode }) {
  const tree = buildPageTree();
  const cfg = getConfig();
  const chrome = cfg.chrome;
  const logo = cfg.brand?.logo;
  const hasMeta = chrome.generated_meta && (cfg.generated_at || cfg.commit_sha);

  // A logo replaces the plain project name in the navbar. The dark variant is
  // swapped with CSS rather than JS so it is correct on first paint.
  const navTitle = logo ? (
    <>
      <img src={logo} alt={cfg.project_name} className="dd-logo dd-logo-light" />
      <img
        src={cfg.brand?.logo_dark || logo}
        alt={cfg.project_name}
        className="dd-logo dd-logo-dark"
      />
    </>
  ) : (
    cfg.project_name
  );

  return (
    <>
      <DocsLayout
        tree={tree}
        nav={{ title: navTitle }}
        sidebar={{
          enabled: chrome.sidebar,
          defaultOpenLevel: chrome.sidebar_default_open_level,
          collapsible: chrome.sidebar_collapsible,
        }}
        githubUrl={cfg.repo?.url || undefined}
        links={chrome.links.map(link => ({
          type: 'main' as const,
          text: link.text,
          url: link.url,
        }))}
        themeSwitch={{ enabled: chrome.theme_switch }}
        searchToggle={{ enabled: chrome.search }}
      >
        {children}
      </DocsLayout>

      {cfg.chatbot.enabled && (
        <ChatbotWidget
          backendUrl={cfg.chatbot.backend_url ?? ''}
          projectName={cfg.project_name}
        />
      )}

      {hasMeta && (
        <div className="dd-gen-meta">
          {cfg.commit_sha && (
            <span className="dd-gen-commit">
              <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                <path d="M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0z" />
              </svg>
              {cfg.commit_sha}
            </span>
          )}
          {cfg.generated_at && <span>{cfg.generated_at}</span>}
          <style>{`
            .dd-gen-meta {
              position: fixed; bottom: 0; left: 0;
              width: var(--fd-sidebar-width, 268px);
              display: flex; align-items: center; gap: 0.5rem;
              padding: 0.4rem 1rem;
              font-size: 0.65rem;
              font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
              color: var(--color-fd-muted-foreground);
              background: var(--color-fd-card, var(--color-fd-background));
              border-top: 1px solid var(--color-fd-border);
              z-index: 10; pointer-events: none;
            }
            .dd-gen-commit { display: flex; align-items: center; gap: 0.3rem; }
            @media (max-width: 768px) { .dd-gen-meta { display: none; } }
          `}</style>
        </div>
      )}
    </>
  );
}
