'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';

interface Evidence {
  id: string;
  file_path: string;
  start_line: number;
  end_line: number;
  snippet: string;
  language: string;
  role: string;
  title: string;
}

interface Reference {
  title: string;
  path: string;
  url: string;
}

interface TraceStep {
  phase: string;
  message: string;
  timestamp: number;
}

interface Turn {
  question: string;
  mode: 'fast' | 'deep';
  answer: string;
  evidence: Evidence[];
  references: Reference[];
  trace: TraceStep[];
  done: boolean;
  error?: string;
}

export default function AskPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [activeTurn, setActiveTurn] = useState<number | null>(null);
  const backendUrlRef = useRef('');
  const answerBottomRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    const w = window as typeof window & { __DD_CONFIG__?: { chatbot?: { backend_url?: string } } };
    backendUrlRef.current = w.__DD_CONFIG__?.chatbot?.backend_url ?? '';
  }, []);

  useEffect(() => {
    answerBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns]);

  const submitQuestion = useCallback(async (q: string, m: 'fast' | 'deep') => {
    const url = backendUrlRef.current;
    if (!q.trim() || !url) return;

    const turnIdx = turns.length;
    setStreaming(true);
    setActiveTurn(turnIdx);
    setTurns(prev => [...prev, {
      question: q, mode: m, answer: '', evidence: [], references: [], trace: [], done: false,
    }]);

    // Build history from previous turns for multi-turn context
    const history = turns.flatMap(t => [
      { role: 'user', content: t.question },
      { role: 'assistant', content: t.answer },
    ]);

    const endpoint = m === 'deep' ? '/deep/stream' : '/query/stream';
    const body = m === 'deep'
      ? { question: q, history, max_rounds: 4 }
      : { question: q, history };

    try {
      const res = await fetch(`${url}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.body) throw new Error('No stream body');

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      let eventType = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
            continue;
          }
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6);
          if (raw === '[DONE]') { eventType = ''; break; }
          try {
            const evt = JSON.parse(raw);
            const type = eventType || evt.type || '';
            eventType = '';

            if (type === 'token') {
              const token = evt.text ?? evt.content ?? '';
              if (token) {
                setTurns(prev => {
                  const next = [...prev];
                  next[turnIdx] = { ...next[turnIdx], answer: next[turnIdx].answer + token };
                  return next;
                });
              }
            } else if (type === 'trace') {
              setTurns(prev => {
                const next = [...prev];
                next[turnIdx] = {
                  ...next[turnIdx],
                  trace: [...next[turnIdx].trace, {
                    phase: evt.phase ?? '',
                    message: evt.message ?? '',
                    timestamp: evt.timestamp ?? 0,
                  }],
                };
                return next;
              });
            } else if (type === 'result') {
              setTurns(prev => {
                const next = [...prev];
                next[turnIdx] = {
                  ...next[turnIdx],
                  evidence: evt.evidence ?? [],
                  references: evt.references ?? [],
                  done: true,
                };
                return next;
              });
            } else if (type === 'error') {
              setTurns(prev => {
                const next = [...prev];
                next[turnIdx] = { ...next[turnIdx], error: evt.detail ?? 'Something went wrong', done: true };
                return next;
              });
            }
          } catch {}
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Connection failed';
      setTurns(prev => {
        const next = [...prev];
        next[turnIdx] = { ...next[turnIdx], error: msg, done: true };
        return next;
      });
    } finally {
      setStreaming(false);
    }
  }, [turns]);

  // Auto-submit from URL ?q= param
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const q = params.get('q');
    const m = (params.get('mode') ?? 'fast') as 'fast' | 'deep';
    if (!q) return;
    const url = new URL(location.href);
    url.searchParams.delete('q');
    url.searchParams.delete('mode');
    history.replaceState(null, '', url.toString());
    const trySubmit = () => {
      if (backendUrlRef.current) submitQuestion(q, m);
      else setTimeout(trySubmit, 50);
    };
    setTimeout(trySubmit, 50);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentTurn = activeTurn !== null ? turns[activeTurn] : null;

  return (
    <div className="dda-root">
      {/* Header */}
      <header className="dda-header">
        <button className="dda-back" onClick={() => router.back()} aria-label="Back to docs">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <path d="M19 12H5M12 5l-7 7 7 7" />
          </svg>
          Back to docs
        </button>
        <div className="dda-header-center">
          {streaming && (
            <span className="dda-header-status">
              <span className="dda-status-dot" />
              Thinking…
            </span>
          )}
        </div>
        <div />
      </header>

      {/* Two-pane body */}
      <div className="dda-body">
        {/* Left — conversation */}
        <main className="dda-main">
          <div className="dda-turns">
            {turns.length === 0 && !streaming && (
              <div className="dda-empty">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" opacity=".25" aria-hidden="true">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <p>Ask anything about this codebase.</p>
                <p className="dda-empty-hint">Use <strong>Fast</strong> for quick answers or <strong>Deep</strong> for thorough research.</p>
              </div>
            )}

            {turns.map((t, i) => (
              <div
                key={i}
                className={`dda-turn${activeTurn === i ? ' dda-turn-active' : ''}`}
                onClick={() => setActiveTurn(i)}
              >
                {/* Question */}
                <div className="dda-q-row">
                  <div className="dda-q">
                    <span className={`dda-mode-badge dda-mode-${t.mode}`}>{t.mode === 'deep' ? 'Deep' : 'Fast'}</span>
                    {t.question}
                  </div>
                </div>

                {/* Answer */}
                <div className="dda-a-block">
                  {t.error ? (
                    <div className="dda-error">{t.error}</div>
                  ) : t.answer ? (
                    <div
                      className="dda-answer"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(t.answer) }}
                    />
                  ) : (
                    <div className="dda-dots"><span /><span /><span /></div>
                  )}
                </div>

                {/* Deep trace — streams in left pane, disappears when done */}
                {t.mode === 'deep' && !t.done && t.trace.length > 0 && (
                  <div className="dda-trace-stream">
                    {t.trace.map((step, si) => (
                      <div key={si} className="dda-trace-item">
                        <span className="dda-trace-phase">{step.phase}</span>
                        <span>{step.message}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <div ref={answerBottomRef} style={{ height: '120px' }} />
          </div>

          {/* Inline ask bar */}
          <AskBar streaming={streaming} onSubmit={submitQuestion} />
        </main>

        {/* Right — sources */}
        <aside className="dda-aside">
          {currentTurn ? (
            <SourcePanel turn={currentTurn} />
          ) : (
            <div className="dda-aside-empty">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity=".3" aria-hidden="true">
                <path d="M9 12h6M9 16h6M7 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3" />
                <rect x="7" y="2" width="10" height="4" rx="1" />
              </svg>
              <p>Sources will appear here after you ask.</p>
            </div>
          )}
        </aside>
      </div>

      <style>{`
        .dda-root {
          display: flex; flex-direction: column;
          height: 100vh; overflow: hidden;
          background: hsl(var(--fd-background));
          color: hsl(var(--fd-foreground));
          font-family: inherit;
        }

        /* ── Header ── */
        .dda-header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 0 1.5rem;
          border-bottom: 1px solid hsl(var(--fd-border));
          flex-shrink: 0; height: 48px;
        }
        .dda-back {
          display: inline-flex; align-items: center; gap: 0.4rem;
          font-size: 0.8125rem; font-weight: 500;
          color: hsl(var(--fd-muted-foreground));
          background: none; border: none; cursor: pointer; padding: 0;
          font-family: inherit; transition: color 0.1s;
        }
        .dda-back:hover { color: hsl(var(--fd-foreground)); }
        .dda-header-center { display: flex; align-items: center; gap: 0.5rem; font-size: 0.8125rem; color: hsl(var(--fd-muted-foreground)); }
        .dda-header-status { display: flex; align-items: center; gap: 0.4rem; }
        .dda-status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--brand, #eb3e25); animation: dda-blink 1.2s ease-in-out infinite; }
        @keyframes dda-blink { 0%,100%{opacity:1} 50%{opacity:0.2} }

        /* ── Two-pane body ── */
        .dda-body { display: flex; flex: 1; overflow: hidden; min-height: 0; }

        /* ── Main (left) pane ── */
        .dda-main { flex: 1; min-width: 0; display: flex; flex-direction: column; border-right: 1px solid hsl(var(--fd-border)); overflow: hidden; }

        /* scrollable content — centred readable column like the docs */
        .dda-turns {
          flex: 1; overflow-y: auto;
          padding: 2rem 2rem 0;
          display: flex; flex-direction: column; gap: 2rem;
        }
        /* centre each turn to a readable max-width */
        .dda-turn, .dda-empty {
          max-width: 760px;
          width: 100%;
          margin-left: auto;
          margin-right: auto;
        }
        .dda-empty {
          display: flex; flex-direction: column; align-items: center;
          justify-content: center; gap: 0.6rem;
          padding: 5rem 1rem; text-align: center;
          color: hsl(var(--fd-muted-foreground)); font-size: 0.9rem;
        }
        .dda-empty p { margin: 0; }
        .dda-empty-hint { font-size: 0.8rem; opacity: 0.7; }
        .dda-empty strong { color: hsl(var(--fd-foreground)); }

        .dda-turn { display: flex; flex-direction: column; gap: 1rem; padding: 1rem; border-radius: 8px; cursor: pointer; transition: background 0.1s; }
        .dda-turn:hover { background: hsl(var(--fd-muted) / 0.5); }
        .dda-turn-active { background: hsl(var(--fd-muted) / 0.6) !important; }

        .dda-q-row { display: flex; justify-content: flex-end; }
        .dda-q {
          display: inline-flex; align-items: flex-start; gap: 0.5rem;
          background: hsl(var(--fd-muted));
          border-radius: 12px 12px 2px 12px;
          padding: 0.75rem 1rem; max-width: 85%;
          font-size: 0.9375rem; font-weight: 500; line-height: 1.5;
        }
        .dda-mode-badge {
          flex-shrink: 0; margin-top: 0.15rem;
          font-size: 0.55rem; font-weight: 700; text-transform: uppercase;
          letter-spacing: 0.07em; border-radius: 4px; padding: 0.15em 0.45em; color: #fff;
        }
        .dda-mode-fast { background: var(--brand, #eb3e25); }
        .dda-mode-deep { background: #7c3aed; }

        .dda-a-block { padding: 0 0.25rem; }
        .dda-answer { font-size: 0.9375rem; line-height: 1.8; color: hsl(var(--fd-foreground)); }
        .dda-answer p { margin: 0.7rem 0; }
        .dda-answer p:first-child { margin-top: 0; }
        .dda-answer ul,.dda-answer ol { padding-left: 1.5rem; margin: 0.6rem 0; }
        .dda-answer li { margin: 0.3rem 0; }
        .dda-answer strong { font-weight: 600; }
        .dda-answer a { color: var(--brand, #eb3e25); text-decoration: none; }
        .dda-answer a:hover { text-decoration: underline; }
        .dda-answer code:not(pre code) { background: hsl(var(--fd-muted)); border-radius: 4px; padding: 0.1em 0.4em; font-size: 0.85em; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        .dda-answer h2 { font-size: 1.1rem; font-weight: 600; margin: 1.25rem 0 0.5rem; }
        .dda-answer h3 { font-size: 1rem; font-weight: 600; margin: 1rem 0 0.4rem; }
        .dda-error { color: #ef4444; font-size: 0.875rem; padding: 0.75rem 1rem; background: color-mix(in srgb, #ef4444 8%, transparent); border-radius: 6px; border-left: 3px solid #ef4444; }
        .dda-dots { display: flex; gap: 5px; padding: 0.5rem 0; }
        .dda-dots span { width: 7px; height: 7px; border-radius: 50%; background: var(--brand, #eb3e25); animation: dda-pulse 1.2s ease-in-out infinite; }
        .dda-dots span:nth-child(2) { animation-delay: 0.2s; }
        .dda-dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes dda-pulse { 0%,60%,100%{opacity:0.2} 30%{opacity:1} }

        /* ── Ask bar — matches the floating widget aesthetic ── */
        .dda-askbar-outer {
          flex-shrink: 0;
          padding: 0 2rem 1.25rem;
        }
        .dda-askbar {
          max-width: 760px; margin: 0 auto;
          background: hsl(var(--fd-background));
          border: 1px solid hsl(var(--fd-border));
          border-radius: 12px;
          box-shadow: 0 4px 20px rgba(0,0,0,0.08), 0 1px 4px rgba(0,0,0,0.04);
          overflow: hidden;
        }
        .dda-askbar-input-wrap { position: relative; padding: 0.75rem 1rem 0.3rem; }
        .dda-askbar-placeholder {
          position: absolute; top: 0.75rem; left: 1rem; right: 1rem;
          pointer-events: none; color: hsl(var(--fd-muted-foreground));
          font-size: 0.9375rem; line-height: 1.5;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .dda-askbar-textarea {
          width: 100%; background: transparent; border: none; outline: none;
          resize: none; font-size: 0.9375rem; line-height: 1.5;
          color: hsl(var(--fd-foreground)); font-family: inherit;
          min-height: 2.5rem; display: block;
        }
        .dda-askbar-row {
          display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
          border-top: 0.5px solid hsl(var(--fd-border));
          padding: 0.35rem 0.75rem 0.35rem 0.5rem;
          height: 2.75rem;
        }
        .dda-askbar-mode {
          display: flex; align-items: center; gap: 0.3rem;
          padding: 0.25rem 0.55rem; border-radius: 6px;
          border: none; background: transparent;
          color: hsl(var(--fd-muted-foreground));
          font-size: 0.8125rem; font-weight: 500; cursor: pointer;
          font-family: inherit; transition: background 0.1s, color 0.1s;
        }
        .dda-askbar-mode:hover { background: hsl(var(--fd-muted)); color: hsl(var(--fd-foreground)); }
        .dda-askbar-send {
          display: flex; align-items: center; justify-content: center;
          width: 2rem; height: 2rem; border-radius: 50%;
          border: none; background: var(--brand, #eb3e25); color: #fff;
          cursor: pointer; flex-shrink: 0; transition: transform 0.1s;
        }
        .dda-askbar-send:hover:not(:disabled) { transform: scale(1.08); }
        .dda-askbar-send:disabled { background: hsl(var(--fd-muted)); color: hsl(var(--fd-muted-foreground)); cursor: default; }

        /* ── Right (sources) pane ── */
        .dda-aside { width: 300px; flex-shrink: 0; overflow-y: auto; padding: 1.25rem 1rem; display: flex; flex-direction: column; gap: 1.25rem; }
        .dda-aside-empty { display: flex; flex-direction: column; align-items: center; gap: 0.75rem; padding: 3rem 1rem; color: hsl(var(--fd-muted-foreground)); font-size: 0.8rem; text-align: center; }
        .dda-aside-empty p { margin: 0; }

        .dda-sources-section { display: flex; flex-direction: column; gap: 0.5rem; }
        .dda-sources-label { font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: hsl(var(--fd-muted-foreground)); margin: 0; }
        .dda-evidence-item { border: 1px solid hsl(var(--fd-border)); border-radius: 6px; overflow: hidden; font-size: 0.75rem; }
        .dda-evidence-head { display: flex; align-items: center; gap: 0.4rem; padding: 0.4rem 0.6rem; background: hsl(var(--fd-muted) / 0.5); border-bottom: 1px solid hsl(var(--fd-border)); }
        .dda-evidence-id { font-size: 0.6rem; font-weight: 700; background: var(--brand, #eb3e25); color: #fff; border-radius: 3px; padding: 0.1em 0.35em; flex-shrink: 0; }
        .dda-evidence-path { font-family: ui-monospace, monospace; font-size: 0.7rem; color: hsl(var(--fd-foreground)); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .dda-evidence-lines { font-size: 0.65rem; color: hsl(var(--fd-muted-foreground)); flex-shrink: 0; }
        .dda-evidence-snippet { padding: 0.5rem 0.6rem; font-family: ui-monospace, monospace; font-size: 0.7rem; line-height: 1.5; background: hsl(var(--fd-background)); color: hsl(var(--fd-foreground)); white-space: pre-wrap; word-break: break-all; max-height: 120px; overflow: hidden; }
        .dda-ref-item { display: flex; align-items: center; gap: 0.4rem; padding: 0.35rem 0; font-size: 0.8rem; color: hsl(var(--fd-muted-foreground)); border-bottom: 1px solid hsl(var(--fd-border) / 0.5); }
        .dda-ref-item:last-child { border-bottom: none; }
        .dda-ref-item a { color: var(--brand, #eb3e25); text-decoration: none; }
        .dda-ref-item a:hover { text-decoration: underline; }

        /* trace — streams in left pane, hidden once done */
        .dda-trace-stream { display: flex; flex-direction: column; gap: 0.2rem; padding: 0.5rem 0.25rem; border-top: 1px dashed hsl(var(--fd-border) / 0.6); margin-top: 0.25rem; }
        .dda-trace-item { display: flex; align-items: flex-start; gap: 0.4rem; font-size: 0.73rem; color: hsl(var(--fd-muted-foreground)); padding: 0.15rem 0; }
        .dda-trace-phase { flex-shrink: 0; font-size: 0.58rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.1em 0.35em; border-radius: 3px; background: hsl(var(--fd-muted)); }

        /* ── Responsive ── */
        @media (max-width: 768px) {
          .dda-aside { display: none; }
          .dda-main { border-right: none; }
          .dda-turns { padding: 1rem 1rem 0; }
          .dda-askbar-outer { padding: 0 1rem 1rem; }
        }
      `}</style>
    </div>
  );
}

/* ── Ask bar component ───────────────────────────────────────────────────────── */

function AskBar({ streaming, onSubmit }: {
  streaming: boolean;
  onSubmit: (q: string, m: 'fast' | 'deep') => void;
}) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'fast' | 'deep'>('fast');

  function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim() || streaming) return;
    onSubmit(query, mode);
    setQuery('');
  }

  return (
    <div className="dda-askbar-outer">
    <form className="dda-askbar" onSubmit={handleSubmit}>
      <div className="dda-askbar-input-wrap">
        {!query && (
          <div className="dda-askbar-placeholder" aria-hidden="true">
            Ask a follow-up…
          </div>
        )}
        <textarea
          className="dda-askbar-textarea"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
          }}
          rows={2}
          disabled={streaming}
          aria-label="Ask a follow-up question"
        />
      </div>
      <div className="dda-askbar-row">
        <button
          type="button"
          className="dda-askbar-mode"
          onClick={() => setMode(m => m === 'fast' ? 'deep' : 'fast')}
        >
          {mode === 'fast' ? (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M13 2L4.5 13.5H11L10 22L20.5 10H14L13 2Z" />
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
            </svg>
          )}
          <span>{mode === 'fast' ? 'Fast' : 'Deep'}</span>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" style={{ opacity: 0.4 }} aria-hidden="true">
            <path d="M7 10l5 5 5-5z" />
          </svg>
        </button>
        <button
          type="submit"
          className="dda-askbar-send"
          disabled={!query.trim() || streaming}
          aria-label="Send"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <path d="M5 12h14M12 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    </form>
    </div>
  );
}

/* ── Source panel ────────────────────────────────────────────────────────────── */

function SourcePanel({ turn }: { turn: Turn }) {
  const hasEvidence = turn.evidence.length > 0;
  const hasRefs = turn.references.length > 0;

  if (!turn.done && !hasEvidence) {
    return (
      <div className="dda-aside-empty">
        <div className="dda-dots"><span /><span /><span /></div>
        <p>{turn.mode === 'deep' ? 'Researching…' : 'Gathering sources…'}</p>
      </div>
    );
  }

  return (
    <>
      {hasEvidence && (
        <div className="dda-sources-section">
          <p className="dda-sources-label">Sources</p>
          {turn.evidence.slice(0, 8).map((e, i) => (
            <div key={i} className="dda-evidence-item">
              <div className="dda-evidence-head">
                <span className="dda-evidence-id">{e.id || `E${i + 1}`}</span>
                <span className="dda-evidence-path">{e.file_path}</span>
                {e.start_line > 0 && (
                  <span className="dda-evidence-lines">:{e.start_line}–{e.end_line}</span>
                )}
              </div>
              {e.snippet && (
                <div className="dda-evidence-snippet">
                  {e.snippet.slice(0, 300)}{e.snippet.length > 300 ? '…' : ''}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {hasRefs && (
        <div className="dda-sources-section">
          <p className="dda-sources-label">References</p>
          {turn.references.slice(0, 6).map((r, i) => (
            <div key={i} className="dda-ref-item">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" style={{ flexShrink: 0 }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              {r.url ? (
                <a href={r.url} target="_blank" rel="noopener">{r.title || r.path}</a>
              ) : (
                <span>{r.title || r.path}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/* ── Markdown renderer ───────────────────────────────────────────────────────── */

function renderMarkdown(md: string): string {
  const parts = md.split(/(```(?:[^\n`]*)?\n[\s\S]*?```)/g);
  return parts.map((part, i) => {
    if (i % 2 === 1) {
      const m = part.match(/```([^\n`]*)?\n([\s\S]*?)```/);
      if (m) {
        const body = m[2].replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return `<pre class="dd-ask-code"><code>${body}</code></pre>`;
      }
      return part;
    }
    return part
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/^#{1,3} (.+)$/gm, (_, t, offset, str) => {
        const level = str.slice(0, offset).match(/\n/) ? 2 : 1;
        return `<h${level + 1}>${t}</h${level + 1}>`;
      })
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`\n]+)`/g, '<code>$1</code>')
      .replace(/\[([^\]\n]+)\]\(([^)\n]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\n\n+/g, '</p><p>')
      .replace(/\n/g, '<br>')
      .replace(/^(.+)$/, '<p>$1</p>');
  }).join('');
}

