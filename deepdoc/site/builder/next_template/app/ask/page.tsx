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
  symbol_names: string[];
  reason: string;
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
  // decompose
  sub_questions?: string[];
  // tool_call
  action?: string;
  path?: string;
  pattern?: string;
  output_preview?: string;
  // step context
  step?: number;
  question?: string;
  // step_done
  sources?: string[];
  chunks_used?: number;
  // retrieve
  retrieved?: number;
}

interface Turn {
  question: string;
  mode: 'fast' | 'deep';
  answer: string;
  evidence: Evidence[];
  references: Reference[];
  trace: TraceStep[];
  file_inventory: string[];
  done: boolean;
  error?: string;
}

interface OpenFile {
  file_path: string;
  start_line: number;
  end_line: number;
  snippet: string;
  language: string;
  title: string;
}

export default function AskPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [openFile, setOpenFile] = useState<OpenFile | null>(null);
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

  // Close modal on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpenFile(null); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const submitQuestion = useCallback(async (q: string, m: 'fast' | 'deep') => {
    const url = backendUrlRef.current;
    if (!q.trim() || !url) return;

    const turnIdx = turns.length;
    setStreaming(true);
    setTurns(prev => [...prev, {
      question: q, mode: m, answer: '', evidence: [], references: [],
      trace: [], file_inventory: [], done: false,
    }]);

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
                    sub_questions: evt.sub_questions,
                    action: evt.action,
                    path: evt.path,
                    pattern: evt.pattern,
                    output_preview: evt.output_preview,
                    step: evt.step,
                    question: evt.question,
                    sources: evt.sources,
                    chunks_used: evt.chunks_used,
                    retrieved: evt.retrieved,
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
                  file_inventory: evt.file_inventory ?? [],
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

  const currentTurn = turns.length > 0 ? turns[turns.length - 1] : null;

  return (
    <div className="dda-root">
      <header className="dda-header">
        <button className="dda-back" onClick={() => router.back()} aria-label="Back to docs">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
            <path d="M19 12H5M12 5l-7 7 7 7" />
          </svg>
          Back to docs
        </button>
        {streaming && (
          <span className="dda-live">
            <span className="dda-live-dot" />
            {currentTurn?.mode === 'deep' ? 'Researching…' : 'Thinking…'}
          </span>
        )}
        <div style={{ width: 90 }} />
      </header>

      <div className="dda-body">
        <main className="dda-main">
          <div className="dda-scroll">
            {turns.length === 0 && (
              <div className="dda-empty">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <p>Ask anything about this codebase</p>
                <p className="dda-empty-sub">Fast for quick answers — Deep for thorough research</p>
              </div>
            )}

            {turns.map((t, i) => (
              <div key={i} className="dda-turn">
                <div className="dda-turn-meta">
                  <h1 className="dda-question">{t.question}</h1>
                  <ModeBadge mode={t.mode} />
                </div>

                <div className="dda-answer-region">
                  {t.error ? (
                    <div className="dda-error">{t.error}</div>
                  ) : t.answer ? (
                    <div className="dda-answer" dangerouslySetInnerHTML={{ __html: renderMarkdown(t.answer) }} />
                  ) : (
                    <Skeleton />
                  )}
                </div>
              </div>
            ))}

            <div ref={answerBottomRef} style={{ height: '160px' }} />
          </div>

          <AskBar streaming={streaming} onSubmit={submitQuestion} />
        </main>

        <aside className="dda-aside">
          {currentTurn
            ? <SourcePanel turn={currentTurn} onOpenFile={setOpenFile} />
            : <EmptyAside />
          }
        </aside>
      </div>

      {openFile && <FileModal file={openFile} onClose={() => setOpenFile(null)} />}

      <style>{`
        /* ── Root ── */
        .dda-root {
          display: flex; flex-direction: column;
          height: 100vh; overflow: hidden;
          background: oklch(96% 0.006 70);
          color: oklch(16% 0.008 70);
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
          font-size: 15px; line-height: 1.5;
        }

        /* ── Header ── */
        .dda-header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 0 1.75rem;
          height: 52px; flex-shrink: 0;
          border-bottom: 1px solid oklch(89% 0.006 70);
        }
        .dda-back {
          display: inline-flex; align-items: center; gap: 6px;
          font-size: 13px; font-weight: 500;
          color: oklch(52% 0.007 70);
          background: none; border: none; cursor: pointer; padding: 0;
          font-family: inherit; transition: color 0.15s;
        }
        .dda-back:hover { color: oklch(18% 0.008 70); }
        .dda-live {
          display: flex; align-items: center; gap: 7px;
          font-size: 12.5px; color: oklch(52% 0.007 70);
        }
        .dda-live-dot {
          width: 6px; height: 6px; border-radius: 50%;
          background: oklch(60% 0.16 50);
          animation: dda-pulse-dot 1.4s ease-in-out infinite;
        }
        @keyframes dda-pulse-dot { 0%,100%{opacity:1} 50%{opacity:0.15} }

        /* ── Body ── */
        .dda-body { display: flex; flex: 1; overflow: hidden; min-height: 0; }

        /* ── Left pane ── */
        .dda-main {
          flex: 1; min-width: 0;
          display: flex; flex-direction: column;
          border-right: 1px solid oklch(89% 0.006 70);
          overflow: hidden;
        }
        .dda-scroll {
          flex: 1; overflow-y: auto;
          padding: 3rem 2.5rem 0;
        }

        /* ── Empty state ── */
        .dda-empty {
          display: flex; flex-direction: column; align-items: center; gap: 10px;
          padding: 7rem 1rem; text-align: center;
          color: oklch(64% 0.007 70); max-width: 340px; margin: 0 auto;
        }
        .dda-empty svg { opacity: 0.22; }
        .dda-empty p { margin: 0; font-size: 14.5px; font-weight: 500; color: oklch(40% 0.008 70); }
        .dda-empty-sub { font-size: 13px; color: oklch(60% 0.007 70); font-weight: 400; }

        /* ── Turn ── */
        .dda-turn { max-width: 660px; margin: 0 auto 3.5rem; }
        .dda-turn-meta { margin-bottom: 1.4rem; }
        .dda-question {
          font-size: 23px; font-weight: 620; line-height: 1.3;
          color: oklch(12% 0.008 70);
          margin: 0 0 0.75rem;
          letter-spacing: -0.015em;
        }

        /* ── Mode badge ── */
        .dda-badge {
          display: inline-flex; align-items: center; gap: 5px;
          font-size: 11.5px; font-weight: 500; letter-spacing: 0.01em;
          border-radius: 20px; padding: 3px 10px 3px 8px;
          border: 1px solid;
        }
        .dda-badge-fast {
          background: oklch(92.5% 0.005 70);
          color: oklch(40% 0.007 70);
          border-color: oklch(86% 0.006 70);
        }
        .dda-badge-deep {
          background: oklch(95.5% 0.04 55);
          color: oklch(46% 0.13 46);
          border-color: oklch(88% 0.07 50);
        }

        /* ── Answer ── */
        .dda-answer {
          font-size: 15px; line-height: 1.8;
          color: oklch(18% 0.008 70);
        }
        .dda-answer p { margin: 0 0 0.9rem; }
        .dda-answer p:last-child { margin-bottom: 0; }
        .dda-answer ul, .dda-answer ol { padding-left: 1.5rem; margin: 0.5rem 0 0.9rem; }
        .dda-answer li { margin: 0.35rem 0; }
        .dda-answer strong { font-weight: 650; }
        .dda-answer a { color: var(--brand, #eb3e25); text-decoration: none; }
        .dda-answer a:hover { text-decoration: underline; }
        .dda-answer code:not(pre code) {
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 0.84em;
          background: oklch(93% 0.006 70);
          border: 1px solid oklch(87% 0.006 70);
          border-radius: 4px; padding: 0.1em 0.4em;
        }
        .dda-answer h2 {
          font-size: 17px; font-weight: 640; margin: 1.75rem 0 0.6rem;
          color: oklch(12% 0.008 70); letter-spacing: -0.01em;
        }
        .dda-answer h3 {
          font-size: 15px; font-weight: 620; margin: 1.25rem 0 0.4rem;
          color: oklch(16% 0.008 70);
        }
        .dd-ask-code {
          background: oklch(16% 0.007 250);
          color: oklch(88% 0.007 70);
          border-radius: 9px;
          padding: 1rem 1.2rem;
          margin: 0.9rem 0;
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 12.5px; line-height: 1.65;
          overflow-x: auto;
        }
        .dda-error {
          font-size: 13.5px; padding: 0.8rem 1rem;
          color: oklch(46% 0.18 24);
          background: oklch(97.5% 0.012 24);
          border: 1px solid oklch(89% 0.04 24);
          border-radius: 7px;
        }

        /* ── Skeleton shimmer ── */
        .dda-skeleton { display: flex; flex-direction: column; gap: 11px; padding: 3px 0; }
        .dda-skel {
          border-radius: 5px; height: 14px;
          background: linear-gradient(
            90deg,
            oklch(91% 0.005 70) 25%,
            oklch(94.5% 0.004 70) 50%,
            oklch(91% 0.005 70) 75%
          );
          background-size: 300% 100%;
          animation: dda-shimmer 1.7s ease-in-out infinite;
        }
        @keyframes dda-shimmer {
          0% { background-position: 100% 0; }
          100% { background-position: -100% 0; }
        }

        /* ── Ask bar ── */
        .dda-bar-wrap {
          flex-shrink: 0;
          padding: 0 2.5rem 1.5rem;
        }
        .dda-bar {
          max-width: 660px; margin: 0 auto;
          background: oklch(99.5% 0.003 70);
          border: 1px solid oklch(87% 0.006 70);
          border-radius: 13px;
          box-shadow: 0 2px 10px oklch(0% 0 0 / 0.06), 0 1px 3px oklch(0% 0 0 / 0.04);
          overflow: hidden;
        }
        .dda-bar-input-wrap { position: relative; padding: 0.75rem 1rem 0.3rem; }
        .dda-bar-placeholder {
          position: absolute; top: 0.75rem; left: 1rem; right: 1rem;
          pointer-events: none;
          color: oklch(66% 0.006 70);
          font-size: 14px; line-height: 1.5;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .dda-bar-textarea {
          width: 100%; background: transparent; border: none; outline: none;
          resize: none; font-size: 14px; line-height: 1.55;
          color: oklch(16% 0.008 70); font-family: inherit;
          min-height: 1.55rem; max-height: 7rem; display: block;
        }
        .dda-bar-toolbar {
          display: flex; align-items: center; justify-content: space-between;
          border-top: 1px solid oklch(91% 0.006 70);
          padding: 0.3rem 0.5rem 0.3rem 0.45rem;
          height: 2.6rem;
        }
        .dda-bar-mode {
          display: inline-flex; align-items: center; gap: 5px;
          padding: 4px 10px 4px 8px; border-radius: 20px;
          border: 1px solid oklch(87% 0.006 70);
          background: oklch(95.5% 0.005 70);
          font-size: 12px; font-weight: 500;
          color: oklch(44% 0.007 70); cursor: pointer;
          font-family: inherit; transition: background 0.12s, color 0.12s;
        }
        .dda-bar-mode:hover { background: oklch(91% 0.006 70); color: oklch(20% 0.008 70); }
        .dda-bar-mode.mode-deep {
          background: oklch(95.5% 0.04 55);
          color: oklch(44% 0.13 46);
          border-color: oklch(87% 0.07 50);
        }
        .dda-bar-send {
          display: flex; align-items: center; justify-content: center;
          width: 30px; height: 30px; border-radius: 50%;
          border: none;
          background: oklch(20% 0.008 70);
          color: oklch(97% 0.004 70);
          cursor: pointer; flex-shrink: 0;
          transition: background 0.12s, transform 0.1s;
        }
        .dda-bar-send:hover:not(:disabled) {
          background: oklch(12% 0.008 70);
          transform: scale(1.06);
        }
        .dda-bar-send:disabled {
          background: oklch(89% 0.005 70);
          color: oklch(62% 0.006 70);
          cursor: default;
        }
        @keyframes dda-spin { to { transform: rotate(360deg); } }

        /* ── Right pane ── */
        .dda-aside {
          width: 320px; flex-shrink: 0;
          overflow-y: auto;
          background: oklch(96% 0.006 70);
        }

        /* Empty aside */
        .dda-aside-empty {
          display: flex; flex-direction: column; align-items: center; gap: 9px;
          padding: 5rem 1.5rem; color: oklch(64% 0.007 70);
          font-size: 13px; text-align: center;
        }
        .dda-aside-empty svg { opacity: 0.22; }
        .dda-aside-empty p { margin: 0; }

        /* ── Trace panel ── */
        .dda-trace-card {
          margin: 1rem;
          background: oklch(99.5% 0.003 70);
          border: 1px solid oklch(89% 0.006 70);
          border-radius: 10px; overflow: hidden;
        }
        .dda-trace-top {
          display: flex; align-items: center; justify-content: space-between;
          padding: 10px 12px 9px;
        }
        .dda-trace-label {
          display: flex; align-items: center; gap: 7px;
          font-size: 12px; font-weight: 600;
          color: oklch(28% 0.008 70);
        }
        .dda-trace-orb {
          width: 7px; height: 7px; border-radius: 50%;
          background: oklch(60% 0.16 50);
          animation: dda-pulse-dot 1.4s ease-in-out infinite;
        }
        .dda-trace-n { font-size: 11px; color: oklch(56% 0.007 70); }
        .dda-trace-bar {
          height: 2px; margin: 0 12px 10px;
          background: oklch(89% 0.006 70);
          border-radius: 2px; overflow: hidden;
        }
        .dda-trace-bar-fill {
          height: 100%;
          background: linear-gradient(90deg, oklch(60% 0.16 50), oklch(68% 0.14 60));
          border-radius: 2px;
          animation: dda-bar-anim 1.8s ease-in-out infinite alternate;
        }
        @keyframes dda-bar-anim {
          0% { width: 30%; opacity: 0.6; }
          100% { width: 85%; opacity: 1; }
        }
        .dda-trace-list { border-top: 1px solid oklch(92% 0.005 70); }
        .dda-trace-row {
          padding: 6px 12px; font-size: 12px;
          color: oklch(40% 0.007 70); line-height: 1.45;
          border-top: 1px solid oklch(94% 0.005 70);
        }
        .dda-trace-row:first-child { border-top: none; }
        .dda-trace-row-main { display: flex; align-items: baseline; gap: 6px; }
        .dda-trace-tag {
          flex-shrink: 0; font-size: 10px; font-weight: 700;
          text-transform: uppercase; letter-spacing: 0.06em;
          background: oklch(92.5% 0.006 70);
          color: oklch(50% 0.007 70);
          border-radius: 3px; padding: 1px 5px;
        }
        .dda-trace-tag-tool {
          background: oklch(95% 0.03 260);
          color: oklch(44% 0.09 260);
        }
        .dda-trace-tag-step {
          background: oklch(95.5% 0.04 55);
          color: oklch(46% 0.13 46);
        }
        .dda-trace-mono {
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 11px; color: oklch(34% 0.009 250);
          background: oklch(93% 0.005 250);
          border-radius: 3px; padding: 0 4px;
          max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
          display: inline-block;
        }
        .dda-trace-subqs { margin: 4px 0 2px 0; padding: 0; list-style: none; }
        .dda-trace-subq {
          font-size: 11px; color: oklch(34% 0.008 70);
          padding: 2px 0 2px 10px;
          position: relative;
        }
        .dda-trace-subq::before {
          content: ''; position: absolute; left: 2px; top: 8px;
          width: 4px; height: 4px; border-radius: 50%;
          background: oklch(68% 0.007 70);
        }

        /* ── File list (right pane after done) ── */
        .dda-pane-section { padding: 1rem; }
        .dda-pane-heading {
          font-size: 10.5px; font-weight: 700; text-transform: uppercase;
          letter-spacing: 0.08em; color: oklch(58% 0.007 70);
          margin: 0 0 6px;
        }
        .dda-file-list { display: flex; flex-direction: column; gap: 2px; }
        .dda-file-row {
          display: flex; align-items: center; gap: 7px;
          padding: 6px 9px; border-radius: 6px;
          cursor: pointer;
          transition: background 0.1s;
          background: oklch(99.5% 0.003 70);
          border: 1px solid oklch(90% 0.006 70);
        }
        .dda-file-row:hover { background: oklch(97% 0.008 70); border-color: oklch(84% 0.008 70); }
        .dda-file-row-icon { color: oklch(60% 0.006 70); flex-shrink: 0; }
        .dda-file-row-info { flex: 1; min-width: 0; }
        .dda-file-row-name {
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 11.5px; color: oklch(22% 0.009 70);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .dda-file-row-sub {
          font-size: 10.5px; color: oklch(58% 0.007 70);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          margin-top: 1px;
        }
        .dda-file-row-lines {
          font-family: ui-monospace, Menlo, monospace;
          font-size: 10px; color: oklch(62% 0.007 70); flex-shrink: 0;
        }
        .dda-file-row-arrow { color: oklch(72% 0.006 70); flex-shrink: 0; }

        /* Inventory file rows (no snippet, smaller) */
        .dda-inv-row {
          display: flex; align-items: center; gap: 6px;
          padding: 5px 8px; border-radius: 5px;
          background: transparent;
          border: none; cursor: default;
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 11px; color: oklch(40% 0.008 70);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .dda-inv-row svg { flex-shrink: 0; color: oklch(68% 0.006 70); }

        /* Ref list */
        .dda-ref {
          display: flex; align-items: center; gap: 6px;
          padding: 5px 0; font-size: 12.5px;
          color: oklch(44% 0.007 70);
          border-bottom: 1px solid oklch(91% 0.005 70);
        }
        .dda-ref:last-child { border-bottom: none; }
        .dda-ref a { color: var(--brand, #eb3e25); text-decoration: none; }
        .dda-ref a:hover { text-decoration: underline; }

        /* ── Aside skeleton ── */
        .dda-aside-skel { padding: 1rem; display: flex; flex-direction: column; gap: 8px; }

        /* ── File modal ── */
        .dda-modal-backdrop {
          position: fixed; inset: 0; z-index: 1000;
          background: oklch(8% 0.008 70 / 0.55);
          backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
          padding: 2rem;
          animation: dda-backdrop-in 0.15s ease-out;
        }
        @keyframes dda-backdrop-in { from { opacity: 0; } to { opacity: 1; } }
        .dda-modal {
          background: oklch(13% 0.007 250);
          border: 1px solid oklch(22% 0.008 250);
          border-radius: 12px;
          width: min(860px, 100%);
          max-height: 80vh;
          display: flex; flex-direction: column;
          box-shadow: 0 24px 60px oklch(0% 0 0 / 0.5);
          animation: dda-modal-in 0.15s ease-out;
          overflow: hidden;
        }
        @keyframes dda-modal-in {
          from { opacity: 0; transform: translateY(8px) scale(0.98); }
          to { opacity: 1; transform: none; }
        }
        .dda-modal-head {
          display: flex; align-items: center; gap: 10px;
          padding: 10px 14px;
          border-bottom: 1px solid oklch(22% 0.008 250);
          flex-shrink: 0;
        }
        .dda-modal-path {
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 12.5px; color: oklch(80% 0.008 70);
          flex: 1; min-width: 0;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .dda-modal-lines {
          font-family: ui-monospace, Menlo, monospace;
          font-size: 11px; color: oklch(52% 0.007 70); flex-shrink: 0;
        }
        .dda-modal-lang {
          font-size: 10.5px; font-weight: 600; text-transform: uppercase;
          letter-spacing: 0.06em; color: oklch(50% 0.007 70);
          background: oklch(20% 0.007 250);
          border-radius: 3px; padding: 2px 6px; flex-shrink: 0;
        }
        .dda-modal-close {
          display: flex; align-items: center; justify-content: center;
          width: 26px; height: 26px; border-radius: 6px;
          background: none; border: none; cursor: pointer;
          color: oklch(52% 0.007 70);
          transition: background 0.1s, color 0.1s;
          flex-shrink: 0;
        }
        .dda-modal-close:hover {
          background: oklch(20% 0.007 250); color: oklch(80% 0.008 70);
        }
        .dda-modal-body {
          overflow-y: auto; flex: 1;
        }
        .dda-modal-code {
          margin: 0; padding: 1.25rem 1.5rem;
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 12.5px; line-height: 1.7;
          color: oklch(85% 0.007 70);
          white-space: pre; tab-size: 2;
          overflow-x: auto;
        }

        /* ── Responsive ── */
        @media (max-width: 900px) {
          .dda-aside { display: none; }
          .dda-main { border-right: none; }
          .dda-scroll { padding: 2rem 1.5rem 0; }
          .dda-bar-wrap { padding: 0 1.5rem 1.25rem; }
        }
      `}</style>
    </div>
  );
}

/* ── Mode badge ──────────────────────────────────────────────────────────────── */

function ModeBadge({ mode }: { mode: 'fast' | 'deep' }) {
  return (
    <span className={`dda-badge dda-badge-${mode}`}>
      {mode === 'fast' ? (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M13 2L4.5 13.5H11L10 22L20.5 10H14L13 2Z" />
        </svg>
      ) : (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
        </svg>
      )}
      {mode === 'fast' ? 'Fast' : 'Deep Research'}
    </span>
  );
}

/* ── Skeleton ────────────────────────────────────────────────────────────────── */

function Skeleton() {
  return (
    <div className="dda-skeleton">
      <div className="dda-skel" style={{ width: '91%' }} />
      <div className="dda-skel" style={{ width: '78%' }} />
      <div className="dda-skel" style={{ width: '95%' }} />
      <div className="dda-skel" style={{ width: '63%' }} />
      <div className="dda-skel" style={{ width: '84%' }} />
      <div className="dda-skel" style={{ width: '55%' }} />
    </div>
  );
}

/* ── Ask bar ─────────────────────────────────────────────────────────────────── */

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
    <div className="dda-bar-wrap">
      <form className="dda-bar" onSubmit={handleSubmit}>
        <div className="dda-bar-input-wrap">
          {!query && (
            <div className="dda-bar-placeholder" aria-hidden="true">Ask a follow-up question…</div>
          )}
          <textarea
            className="dda-bar-textarea"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
            }}
            rows={1}
            disabled={streaming}
            aria-label="Ask a follow-up question"
          />
        </div>
        <div className="dda-bar-toolbar">
          <button
            type="button"
            className={`dda-bar-mode${mode === 'deep' ? ' mode-deep' : ''}`}
            onClick={() => setMode(m => m === 'fast' ? 'deep' : 'fast')}
          >
            {mode === 'fast' ? (
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M13 2L4.5 13.5H11L10 22L20.5 10H14L13 2Z" />
              </svg>
            ) : (
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
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
            className="dda-bar-send"
            disabled={!query.trim() || streaming}
            aria-label="Send"
          >
            {streaming ? (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ animation: 'dda-spin 0.75s linear infinite' }} aria-hidden="true">
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
            ) : (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ── Empty aside ─────────────────────────────────────────────────────────────── */

function EmptyAside() {
  return (
    <div className="dda-aside-empty">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
        <path d="M9 12h6M9 16h6M7 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3" />
        <rect x="7" y="2" width="10" height="4" rx="1" />
      </svg>
      <p>Sources appear here</p>
    </div>
  );
}

/* ── Trace row renderer ──────────────────────────────────────────────────────── */

function TraceRow({ step }: { step: TraceStep }) {
  const { phase, message, sub_questions, action, path, pattern, sources } = step;

  const tagClass = (phase === 'tool_call' || phase === 'tool_result')
    ? 'dda-trace-tag dda-trace-tag-tool'
    : (phase === 'step_start' || phase === 'step_done')
    ? 'dda-trace-tag dda-trace-tag-step'
    : 'dda-trace-tag';

  // Tool call: show action + path/pattern inline
  if (phase === 'tool_call' && (path || pattern)) {
    const label = action === 'read_file' ? 'read' : action === 'grep' ? 'grep' : action ?? 'tool';
    const target = path || pattern || '';
    const short = target.split('/').slice(-2).join('/');
    return (
      <div className="dda-trace-row">
        <div className="dda-trace-row-main">
          <span className={tagClass}>{label}</span>
          <span className="dda-trace-mono" title={target}>{short}</span>
        </div>
      </div>
    );
  }

  // Decompose: show sub-questions list
  if (phase === 'decompose' && sub_questions && sub_questions.length > 0) {
    return (
      <div className="dda-trace-row">
        <div className="dda-trace-row-main">
          <span className={tagClass}>{phase}</span>
          <span>{message}</span>
        </div>
        <ul className="dda-trace-subqs">
          {sub_questions.map((q, i) => (
            <li key={i} className="dda-trace-subq">{q}</li>
          ))}
        </ul>
      </div>
    );
  }

  // Step done: show sources found
  if (phase === 'step_done' && sources && sources.length > 0) {
    return (
      <div className="dda-trace-row">
        <div className="dda-trace-row-main">
          <span className={tagClass}>{phase}</span>
          <span>{sources.length} file{sources.length !== 1 ? 's' : ''} found</span>
        </div>
        <ul className="dda-trace-subqs">
          {sources.slice(0, 4).map((s, i) => (
            <li key={i} className="dda-trace-subq" style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 10.5 }}>
              {s.split('/').slice(-2).join('/')}
            </li>
          ))}
          {sources.length > 4 && (
            <li className="dda-trace-subq" style={{ color: 'oklch(60% 0.007 70)' }}>+{sources.length - 4} more</li>
          )}
        </ul>
      </div>
    );
  }

  // Default
  return (
    <div className="dda-trace-row">
      <div className="dda-trace-row-main">
        {phase && <span className={tagClass}>{phase}</span>}
        <span>{message || phase}</span>
      </div>
    </div>
  );
}

/* ── Source panel ────────────────────────────────────────────────────────────── */

function SourcePanel({ turn, onOpenFile }: {
  turn: Turn;
  onOpenFile: (f: OpenFile) => void;
}) {
  const hasEvidence = turn.evidence.length > 0;
  const hasRefs = turn.references.length > 0;
  const hasInventory = turn.file_inventory.length > 0;
  const showTrace = !turn.answer && !turn.done && turn.mode === 'deep' && turn.trace.length > 0;
  const showSkeleton = !turn.done && !hasEvidence && !showTrace;

  return (
    <>
      {/* Trace: during research, before answer starts */}
      {showTrace && (
        <div className="dda-trace-card">
          <div className="dda-trace-top">
            <span className="dda-trace-label">
              <span className="dda-trace-orb" />
              Analyzing codebase
            </span>
            <span className="dda-trace-n">{turn.trace.length}</span>
          </div>
          <div className="dda-trace-bar">
            <div className="dda-trace-bar-fill" />
          </div>
          <div className="dda-trace-list">
            {turn.trace.map((s, i) => <TraceRow key={i} step={s} />)}
          </div>
        </div>
      )}

      {/* Skeleton: fast mode loading */}
      {showSkeleton && (
        <div className="dda-aside-skel">
          <div className="dda-skel" style={{ width: '55%', height: 11 }} />
          <div className="dda-skel" style={{ width: '100%', height: 40, borderRadius: 6 }} />
          <div className="dda-skel" style={{ width: '100%', height: 40, borderRadius: 6 }} />
          <div className="dda-skel" style={{ width: '45%', height: 11, marginTop: 4 }} />
          <div className="dda-skel" style={{ width: '100%', height: 40, borderRadius: 6 }} />
        </div>
      )}

      {/* Evidence: clickable file rows */}
      {hasEvidence && (
        <div className="dda-pane-section">
          <p className="dda-pane-heading">Sources ({turn.evidence.length})</p>
          <div className="dda-file-list">
            {turn.evidence.map((e, i) => {
              const name = e.file_path.split('/').pop() ?? e.file_path;
              const dir = e.file_path.includes('/')
                ? e.file_path.split('/').slice(0, -1).join('/')
                : '';
              return (
                <button
                  key={i}
                  className="dda-file-row"
                  onClick={() => onOpenFile({
                    file_path: e.file_path,
                    start_line: e.start_line,
                    end_line: e.end_line,
                    snippet: e.snippet,
                    language: e.language,
                    title: e.title,
                  })}
                  title={`${e.file_path}:${e.start_line}–${e.end_line}`}
                >
                  <span className="dda-file-row-icon">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                  </span>
                  <span className="dda-file-row-info">
                    <div className="dda-file-row-name">{name}</div>
                    {dir && <div className="dda-file-row-sub">{dir}</div>}
                  </span>
                  {e.start_line > 0 && (
                    <span className="dda-file-row-lines">:{e.start_line}</span>
                  )}
                  <span className="dda-file-row-arrow">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* File inventory (all files researched, no snippets) */}
      {hasInventory && (
        <div className="dda-pane-section" style={{ paddingTop: hasEvidence ? 0 : undefined }}>
          <p className="dda-pane-heading">Also researched</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {turn.file_inventory.map((f, i) => (
              <div key={i} className="dda-inv-row">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                {f.split('/').slice(-2).join('/')}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* References */}
      {hasRefs && (
        <div className="dda-pane-section" style={{ paddingTop: (hasEvidence || hasInventory) ? 0 : undefined }}>
          <p className="dda-pane-heading">References</p>
          {turn.references.map((r, i) => (
            <div key={i} className="dda-ref">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" style={{ flexShrink: 0 }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              {r.url
                ? <a href={r.url} target="_blank" rel="noopener">{r.title || r.path}</a>
                : <span>{r.title || r.path}</span>
              }
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/* ── File modal ──────────────────────────────────────────────────────────────── */

function FileModal({ file, onClose }: { file: OpenFile; onClose: () => void }) {
  const lang = file.language || file.file_path.split('.').pop() || '';
  const escaped = file.snippet
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  return (
    <div
      className="dda-modal-backdrop"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label={file.file_path}
    >
      <div className="dda-modal">
        <div className="dda-modal-head">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="oklch(52% 0.007 70)" strokeWidth="2" aria-hidden="true" style={{ flexShrink: 0 }}>
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <span className="dda-modal-path">{file.file_path}</span>
          {file.start_line > 0 && (
            <span className="dda-modal-lines">:{file.start_line}–{file.end_line}</span>
          )}
          {lang && <span className="dda-modal-lang">{lang}</span>}
          <button className="dda-modal-close" onClick={onClose} aria-label="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="dda-modal-body">
          <pre className="dda-modal-code" dangerouslySetInnerHTML={{ __html: escaped }} />
        </div>
      </div>
    </div>
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
