'use client';

import { useState, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';

interface ChatbotWidgetProps {
  backendUrl: string;
  projectName: string;
}

export function ChatbotWidget({ projectName }: ChatbotWidgetProps) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'fast' | 'deep'>('fast');
  const pathname = usePathname();
  const router = useRouter();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // /ask has its own inline input bar — hide the floating widget there
  if (pathname === '/ask') return null;

  function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    const params = new URLSearchParams({ q: query, mode });
    router.push(`/ask?${params.toString()}`);
    setQuery('');
  }

  return (
    <div className="dd-bar-wrap">
      <form className="dd-bar" onSubmit={handleSubmit}>
        {/* Input area */}
        <div className="dd-bar-input-area">
          {!query && (
            <div className="dd-bar-placeholder" aria-hidden="true">
              Ask {projectName} anything…
            </div>
          )}
          <textarea
            ref={textareaRef}
            className="dd-bar-textarea"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            rows={2}
            aria-label={`Ask ${projectName} anything`}
          />
        </div>

        {/* Toolbar */}
        <div className="dd-bar-toolbar">
          <button
            type="button"
            className="dd-bar-mode"
            onClick={() => setMode(m => (m === 'fast' ? 'deep' : 'fast'))}
          >
            {mode === 'fast' ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M13 2L4.5 13.5H11L10 22L20.5 10H14L13 2Z" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
              </svg>
            )}
            <span>{mode === 'fast' ? 'Fast' : 'Deep'}</span>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style={{ opacity: 0.4 }}>
              <path d="M7 10l5 5 5-5z" />
            </svg>
          </button>

          <button
            type="submit"
            className="dd-bar-send"
            disabled={!query.trim()}
            aria-label="Send"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </form>

      <style>{`
        .dd-bar-wrap {
          position: fixed;
          bottom: 0;
          /* Use fumadocs-ui's own layout vars so the bar sits exactly over
             the docs content area on every screen size.
             --fd-sidebar-width and --fd-toc-width collapse to 0px on mobile
             automatically — no media query needed for that. */
          left: calc(var(--fd-layout-offset, 0px) + var(--fd-sidebar-width, 0px));
          right: var(--fd-toc-width, 0px);
          z-index: 40;
          display: flex;
          justify-content: center;
          padding: 0 1.5rem 1.5rem;
          pointer-events: none;
        }
        .dd-bar {
          pointer-events: all;
          width: 100%;
          max-width: 860px;
          background: hsl(var(--fd-background));
          border: 1px solid hsl(var(--fd-border));
          border-radius: 12px;
          box-shadow: 0 8px 40px rgba(0,0,0,0.14), 0 2px 8px rgba(0,0,0,0.07);
          backdrop-filter: blur(10px);
          overflow: hidden;
        }
        .dd-bar-input-area {
          position: relative;
          padding: 0.75rem 1rem 0.3rem;
        }
        .dd-bar-placeholder {
          position: absolute;
          top: 0.75rem;
          left: 1rem;
          right: 1rem;
          pointer-events: none;
          color: hsl(var(--fd-muted-foreground));
          font-size: 0.9375rem;
          line-height: 1.5;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .dd-bar-textarea {
          width: 100%;
          background: transparent;
          border: none;
          outline: none;
          resize: none;
          font-size: 0.9375rem;
          line-height: 1.5;
          color: hsl(var(--fd-foreground));
          font-family: inherit;
          min-height: 2.8rem;
          display: block;
        }
        .dd-bar-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          border-top: 0.5px solid hsl(var(--fd-border));
          padding: 0.35rem 0.6rem 0.35rem 0.5rem;
          height: 2.75rem;
        }
        .dd-bar-mode {
          display: flex;
          align-items: center;
          gap: 0.3rem;
          padding: 0.25rem 0.55rem;
          border-radius: 6px;
          border: none;
          background: transparent;
          color: hsl(var(--fd-muted-foreground));
          font-size: 0.8125rem;
          font-weight: 500;
          cursor: pointer;
          font-family: inherit;
          transition: background 0.1s, color 0.1s;
        }
        .dd-bar-mode:hover {
          background: hsl(var(--fd-muted));
          color: hsl(var(--fd-foreground));
        }
        .dd-bar-send {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 2rem;
          height: 2rem;
          border-radius: 50%;
          border: none;
          background: var(--brand, #eb3e25);
          color: #fff;
          cursor: pointer;
          transition: opacity 0.15s, transform 0.1s;
          flex-shrink: 0;
        }
        .dd-bar-send:hover:not(:disabled) { transform: scale(1.08); }
        .dd-bar-send:disabled {
          background: hsl(var(--fd-muted));
          color: hsl(var(--fd-muted-foreground));
          cursor: default;
        }
        @media (max-width: 640px) {
          .dd-bar-wrap { padding: 0 0.5rem 0.75rem; }
          .dd-bar { border-radius: 10px; }
        }
      `}</style>
    </div>
  );
}
