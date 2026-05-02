from .common import *


def _chatbot_config_ts(repo_root: Path, cfg: dict[str, Any]) -> str:
    chatbot_cfg = cfg.get("chatbot", {})
    return dedent(
        f"""\
        const envApiBaseUrl = process.env.NEXT_PUBLIC_DEEPDOC_CHATBOT_BASE_URL?.trim() ?? '';

        export const chatbotConfig = {{
          enabled: {str(bool(chatbot_cfg.get("enabled", False))).lower()},
          apiBaseUrl: envApiBaseUrl || {chatbot_site_api_base_url(cfg)!r},
        }};
        """
    )


def _chatbot_toggle_tsx() -> str:
    return dedent(
        """\
        'use client';

        import { startTransition, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
        import { usePathname, useRouter } from 'next/navigation';
        import { chatbotConfig } from '@/lib/chatbot-config';

        function buildAskUrl(question: string, from: string, mode: 'fast' | 'deep' | 'code' = 'fast') {
          const params = new URLSearchParams({
            q: question,
            from: from || '/',
            mode,
          });
          return `/ask?${params.toString()}`;
        }

        export function ChatbotToggle() {
          const pathname = usePathname();
          const router = useRouter();
          const isEnabledOnPage = chatbotConfig.enabled && pathname !== '/ask';
          const [question, setQuestion] = useState('');
          const [mode, setMode] = useState<'fast' | 'deep' | 'code'>('fast');
          const [isDockVisible, setIsDockVisible] = useState(true);
          const lastScrollYRef = useRef(0);

          useEffect(() => {
            if (!isEnabledOnPage) return;
            if (typeof window === 'undefined') return;

            lastScrollYRef.current = window.scrollY;

            let ticking = false;
            const threshold = 18;

            const syncVisibility = () => {
              ticking = false;
              const nextY = window.scrollY;
              const delta = nextY - lastScrollYRef.current;
              if (Math.abs(delta) < threshold) return;

              if (nextY < 24) {
                setIsDockVisible(true);
                lastScrollYRef.current = nextY;
                return;
              }

              setIsDockVisible(delta < 0);
              lastScrollYRef.current = nextY;
            };

            const onScroll = () => {
              if (ticking) return;
              ticking = true;
              window.requestAnimationFrame(syncVisibility);
            };

            window.addEventListener('scroll', onScroll, { passive: true });

            return () => {
              window.removeEventListener('scroll', onScroll);
            };
          }, [isEnabledOnPage]);

          if (!isEnabledOnPage) return null;

          function submit(event?: FormEvent<HTMLFormElement>) {
            event?.preventDefault();
            const trimmed = question.trim();
            if (!trimmed) return;
            setQuestion('');
            startTransition(() => {
              router.push(buildAskUrl(trimmed, pathname || '/', mode));
            });
          }

          return (
            <div className={`deepdoc-chatbot-shell ${isDockVisible ? 'deepdoc-chatbot-shell--visible' : 'deepdoc-chatbot-shell--hidden'}`}>
              <form className="deepdoc-chatbot-dock" onSubmit={submit}>
                <div className="deepdoc-chatbot-dock__meta">
                  <div className="min-w-0">
                    <p className="deepdoc-chatbot-dock__eyebrow">Ask the codebase</p>
                    <p className="text-sm font-medium text-fd-muted-foreground">
                      Open a dedicated answer page with grounded citations.
                    </p>
                  </div>
                  <p className="deepdoc-chatbot-dock__hint">
                    Ask from any docs page and keep reading without losing context.
                  </p>
                </div>
                <div className="mb-3 flex items-center gap-2">
                  <button
                    className={`deepdoc-chatbot-mode-toggle ${mode === 'fast' ? 'deepdoc-chatbot-mode-toggle--active' : ''}`}
                    onClick={() => setMode('fast')}
                    type="button"
                  >
                    Fast
                  </button>
                  <button
                    className={`deepdoc-chatbot-mode-toggle ${mode === 'deep' ? 'deepdoc-chatbot-mode-toggle--active' : ''}`}
                    onClick={() => setMode('deep')}
                    type="button"
                  >
                    Deep Research
                  </button>
                  <button
                    className={`deepdoc-chatbot-mode-toggle ${mode === 'code' ? 'deepdoc-chatbot-mode-toggle--active' : ''}`}
                    onClick={() => setMode('code')}
                    type="button"
                  >
                    Code Aware
                  </button>
                </div>
                <div className="deepdoc-chatbot-dock__row">
                  <textarea
                    className="deepdoc-chatbot-dock__input text-sm"
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                      if (event.nativeEvent.isComposing) return;
                      if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        event.currentTarget.form?.requestSubmit();
                      }
                    }}
                    placeholder="Where is auth handled? How is deployment configured?"
                    rows={1}
                    value={question}
                  />
                  <button className="deepdoc-chatbot-dock__submit text-sm font-semibold" type="submit">
                    Ask
                  </button>
                </div>
              </form>
            </div>
          );
        }
        """
    )


def _chatbot_panel_tsx() -> str:
    return dedent(
        """\
        'use client';

        import Link from 'next/link';
        import { isValidElement, startTransition, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
        import { useRouter, useSearchParams } from 'next/navigation';
        import ReactMarkdown from 'react-markdown';
        import { chatbotConfig } from '@/lib/chatbot-config';

        type CitationEntry = {
          evidence_id?: string;
          file_path: string;
          start_line: number;
          end_line: number;
          text?: string;
          language?: string;
          symbol_names?: string[];
          artifact_type?: string;
          reason?: string;
          source_kind?: string;
        };

        type EvidenceEntry = {
          id: string;
          kind: 'source' | 'config';
          file_path: string;
          start_line: number;
          end_line: number;
          snippet: string;
          role?: string;
          confidence?: number;
          title?: string;
          language?: string;
          symbol_names?: string[];
          source_kind?: string;
          reason?: string;
        };

        type ReferenceEntry = {
          kind: 'generated_doc' | 'repo_doc';
          path: string;
          title: string;
          url?: string;
        };

        type LoadedSyntaxHighlighter = {
          Component: any;
          style: Record<string, unknown>;
        };

        type ChatResponse = {
          answer: string;
          code_citations: CitationEntry[];
          artifact_citations: CitationEntry[];
          evidence?: EvidenceEntry[];
          references?: ReferenceEntry[];
          diagnostics?: Record<string, unknown>;
          doc_links: Array<{
            title: string;
            url: string;
            doc_path: string;
          }>;
          used_chunks: number;
          confidence?: string;
          response_mode?: 'fast' | 'default' | 'deep' | 'code_deep';
          research_mode?: 'deep' | 'code_deep';
          research_sources?: string[];
          trace?: TraceEntry[];
          file_inventory?: FileInventoryEntry[];
        };

        type TraceEntry = {
          index?: number;
          phase: string;
          message: string;
          mode?: string;
          timestamp?: number;
          step?: number;
          max_rounds?: number;
          sub_question_count?: number;
          question?: string;
          action?: string;
          path?: string;
          pattern?: string;
          output_preview?: string;
          retrieved?: number;
          fallback_hits?: number;
          source_count?: number;
          confidence?: string;
        };

        type FileInventoryEntry = {
          file_path: string;
          score: number;
          reasons: string[];
          source_kind?: string;
          publication_tier?: string;
          symbol_names?: string[];
          line_ranges?: string[];
        };

        type ChatHistoryItem = {
          role: 'user' | 'assistant';
          content: string;
        };

        function buildAskUrl(question: string, from: string, mode: 'fast' | 'deep' | 'code' = 'fast') {
          const params = new URLSearchParams({
            q: question,
            from: from || '/',
            mode,
          });
          return `/ask?${params.toString()}`;
        }

        function parseSseChunk(buffer: string) {
          const blocks = buffer.split('\\n\\n');
          const complete = blocks.slice(0, -1);
          const remainder = blocks[blocks.length - 1] || '';
          const events: Array<{ event: string; data: string }> = [];
          for (const block of complete) {
            let event = 'message';
            const data: string[] = [];
            for (const line of block.split('\\n')) {
              if (line.startsWith('event:')) {
                event = line.slice(6).trim() || 'message';
              } else if (line.startsWith('data:')) {
                data.push(line.slice(5).trim());
              }
            }
            events.push({ event, data: data.join('\\n') });
          }
          return { events, remainder };
        }

        function toTraceLine(entry: TraceEntry): string {
          if (entry.phase === 'tool_call') {
            if (entry.action === 'grep') {
              const pattern = entry.pattern ? `"${entry.pattern}"` : 'pattern';
              const scope = entry.path ? ` in ${entry.path}` : '';
              return `Searched ${pattern}${scope}`;
            }
            if (entry.action === 'read_file') {
              return `Read ${entry.path || 'a file'}`;
            }
            return `Ran ${entry.action || 'tool'}${entry.path ? ` on ${entry.path}` : ''}`;
          }
          if (entry.phase === 'retrieve') {
            return `Retrieved ${entry.retrieved ?? 0} indexed chunks`;
          }
          if (entry.phase === 'fallback_start') {
            return 'Indexed evidence looked weak, checking archived source';
          }
          if (entry.phase === 'fallback_done') {
            return `Added ${entry.fallback_hits ?? 0} archived-source hits`;
          }
          if (entry.phase === 'step_start') {
            return `Working on step ${entry.step ?? '?'}${entry.question ? `: ${entry.question}` : ''}`;
          }
          if (entry.phase === 'step_done') {
            return `Completed step ${entry.step ?? '?'}`;
          }
          if (entry.phase === 'decompose') {
            return `Planned ${entry.sub_question_count ?? '?'} focused research steps`;
          }
          if (entry.phase === 'synthesise_start') {
            return 'Synthesizing final answer';
          }
          if (entry.phase === 'done') {
            return 'Answer ready';
          }
          return entry.message;
        }

        function traceHeader(trace: TraceEntry[]) {
          const latest = trace[trace.length - 1];
          if (!latest) {
            return { title: 'Analyzing code', current: 0, total: 0, progressPct: 8 };
          }

          let total = 0;
          let current = 0;
          for (const entry of trace) {
            if (typeof entry.sub_question_count === 'number') {
              total = Math.max(total, entry.sub_question_count);
            }
            if (typeof entry.max_rounds === 'number') {
              total = Math.max(total, entry.max_rounds);
            }
            if (typeof entry.step === 'number') {
              current = Math.max(current, entry.step);
            }
          }

          const inferred = trace.filter((entry) => entry.phase === 'step_start').length;
          if (!total) total = inferred;
          if (!current && latest.phase !== 'start') current = inferred;
          if (latest.phase === 'done') current = Math.max(current, total || 1);

          const normalizedTotal = Math.max(total, 1);
          const normalizedCurrent = Math.max(Math.min(current || 1, normalizedTotal), 1);
          const title = latest.phase === 'done'
            ? 'Answer ready'
            : latest.phase === 'synthesise_start'
              ? 'Synthesizing answer'
              : latest.phase === 'decompose'
                ? 'Planning research'
                : 'Analyzing code';

          return {
            title,
            current: normalizedCurrent,
            total: normalizedTotal,
            progressPct: Math.max(8, Math.round((normalizedCurrent / normalizedTotal) * 100)),
          };
        }

        function formatLines(startLine: number, endLine: number) {
          return startLine === endLine ? `Line ${startLine}` : `Lines ${startLine}-${endLine}`;
        }

        function citationFromEvidence(evidence: EvidenceEntry): CitationEntry {
          return {
            evidence_id: evidence.id,
            file_path: evidence.file_path,
            start_line: evidence.start_line,
            end_line: evidence.end_line,
            text: evidence.snippet,
            language: evidence.language,
            symbol_names: evidence.symbol_names,
            reason: evidence.reason || evidence.role,
            source_kind: evidence.source_kind || evidence.kind,
          };
        }

        function workspaceCitations(response: ChatResponse): CitationEntry[] {
          if (response.evidence?.length) {
            return response.evidence.map(citationFromEvidence);
          }
          return [...(response.code_citations || []), ...(response.artifact_citations || [])].filter(
            (citation) => citation.file_path && !citation.file_path.startsWith('docs/') && !citation.file_path.startsWith('.deepdoc'),
          );
        }

        function referenceLinks(response: ChatResponse) {
          if (response.references?.length) {
            return response.references.map((ref) => ({
              title: ref.title || ref.path,
              url: ref.url || '#',
              doc_path: ref.path,
              kind: ref.kind,
            }));
          }
          return response.doc_links || [];
        }

        function diagnosticsMessages(response: ChatResponse): string[] {
          const diagnostics = response.diagnostics || {};
          const messages: string[] = [];
          for (const key of ['validation_errors', 'warnings', 'missing_evidence', 'rejected_paths']) {
            const value = diagnostics[key];
            if (Array.isArray(value) && value.length) {
              messages.push(`${key.replaceAll('_', ' ')}: ${value.join(', ')}`);
            }
          }
          if (diagnostics.validation_failed_closed) {
            messages.push('validation failed closed');
          }
          return messages;
        }

        function answerWithEvidenceLinks(answer: string): string {
          return answer.replace(/\\[(E\\d+)\\]/g, '[$1](#evidence-$1)');
        }

        function extractCodeLanguage(node: ReactNode): string {
          const target = Array.isArray(node) ? node[0] : node;
          if (!isValidElement(target)) return '';
          const props = target.props as { className?: string };
          const className = typeof props.className === 'string' ? props.className : '';
          const match = className.match(/language-([\\w-]+)/);
          return match?.[1] ?? '';
        }

        function nodeText(node: ReactNode): string {
          if (node == null || typeof node === 'boolean') return '';
          if (typeof node === 'string' || typeof node === 'number') return String(node);
          if (Array.isArray(node)) return node.map(nodeText).join('');
          if (!isValidElement(node)) return '';
          const props = node.props as { children?: ReactNode };
          return nodeText(props.children);
        }

        let syntaxHighlighterPromise: Promise<LoadedSyntaxHighlighter> | null = null;

        function loadSyntaxHighlighter(): Promise<LoadedSyntaxHighlighter> {
          if (!syntaxHighlighterPromise) {
            syntaxHighlighterPromise = Promise.all([
              import('react-syntax-highlighter'),
              import('react-syntax-highlighter/dist/esm/styles/prism'),
            ]).then(([syntaxModule, styleModule]) => ({
              Component: syntaxModule.Prism,
              style: styleModule.oneDark,
            }));
          }
          return syntaxHighlighterPromise;
        }

        function useSyntaxHighlighter() {
          const [syntaxHighlighter, setSyntaxHighlighter] = useState<LoadedSyntaxHighlighter | null>(null);

          useEffect(() => {
            let cancelled = false;

            loadSyntaxHighlighter()
              .then((loaded) => {
                if (!cancelled) {
                  setSyntaxHighlighter(loaded);
                }
              })
              .catch(() => {
                if (!cancelled) {
                  setSyntaxHighlighter(null);
                }
              });

            return () => {
              cancelled = true;
            };
          }, []);

          return syntaxHighlighter;
        }

        function highlightLanguage(language: string): string {
          return !language || language === 'code' ? 'text' : language;
        }

        function HighlightedCodeBlock({
          code,
          language,
          className,
          showLineNumbers = false,
          startingLineNumber = 1,
          lineNumberMinWidth = '3ch',
          padding = '1rem 1.05rem 1.1rem',
        }: {
          code: string;
          language: string;
          className: string;
          showLineNumbers?: boolean;
          startingLineNumber?: number;
          lineNumberMinWidth?: string;
          padding?: string;
        }) {
          const syntaxHighlighter = useSyntaxHighlighter();
          const SyntaxHighlighter = syntaxHighlighter?.Component;
          const normalizedCode = code || ' ';

          if (!SyntaxHighlighter) {
            return (
              <pre className={className}>
                <code>{normalizedCode}</code>
              </pre>
            );
          }

          return (
            <div className={className}>
              <SyntaxHighlighter
                language={highlightLanguage(language)}
                style={syntaxHighlighter.style}
                showLineNumbers={showLineNumbers}
                wrapLongLines={false}
                startingLineNumber={startingLineNumber}
                PreTag="div"
                customStyle={{
                  margin: 0,
                  background: 'transparent',
                  padding,
                  overflowX: 'auto',
                  fontSize: '0.88rem',
                  lineHeight: '1.72',
                }}
                codeTagProps={{
                  style: {
                    fontFamily: "'SF Mono', 'Fira Code', 'JetBrains Mono', 'Menlo', monospace",
                    whiteSpace: 'pre',
                  },
                }}
                lineNumberStyle={{
                  minWidth: lineNumberMinWidth,
                  paddingRight: '1rem',
                  marginRight: '1rem',
                  color: '#6c7086',
                  borderRight: '1px solid rgba(255, 255, 255, 0.06)',
                  textAlign: 'right',
                  userSelect: 'none',
                }}
              >
                {normalizedCode}
              </SyntaxHighlighter>
            </div>
          );
        }

        function AnswerPre({ children }: { children?: ReactNode }) {
          const language = extractCodeLanguage(children) || 'code';
          const code = nodeText(children).replace(/\\n$/, '');

          return (
            <div className="deepdoc-chatbot-answer__pre">
              <div className="deepdoc-chatbot-answer__pre-header">
                <span className="deepdoc-chatbot-answer__pre-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
                <span className="deepdoc-chatbot-answer__pre-label">{language}</span>
              </div>
              <HighlightedCodeBlock
                code={code}
                language={language}
                className="deepdoc-chatbot-answer__syntax"
              />
            </div>
          );
        }

        type ParsedChunk = {
          code: string;
          symbols: string[];
          signature: string;
          imports: string[];
        };

        function parseChunkText(text: string): ParsedChunk {
          const sep = text.indexOf('\\n\\n');
          const headerBlock = sep !== -1 ? text.slice(0, sep) : '';
          const code = sep !== -1 ? text.slice(sep + 2).trim() : text.trim();

          let symbols: string[] = [];
          let signature = '';
          let imports: string[] = [];

          for (const line of headerBlock.split('\\n')) {
            if (line.startsWith('Symbols: ')) {
              symbols = line.slice(9).split(',').map(s => s.trim()).filter(Boolean);
            } else if (line.startsWith('Signature: ')) {
              signature = line.slice(11).trim();
            } else if (line.startsWith('Imports: ')) {
              imports = line.slice(9).split(',').map(s => s.trim()).filter(Boolean);
            }
          }

          return { code, symbols, signature, imports };
        }

        function inferLanguage(filePath: string): string {
          const ext = filePath.split('.').pop()?.toLowerCase() || '';
          const map: Record<string, string> = {
            py: 'python', ts: 'typescript', tsx: 'tsx', js: 'javascript',
            jsx: 'jsx', rs: 'rust', go: 'go', java: 'java', rb: 'ruby',
            yml: 'yaml', yaml: 'yaml', json: 'json', md: 'markdown',
            sql: 'sql', sh: 'bash', bash: 'bash', css: 'css', html: 'html',
            dockerfile: 'dockerfile', toml: 'toml', xml: 'xml',
          };
          return map[ext] || 'text';
        }

        function CodeModal({
          citation,
          onClose,
        }: {
          citation: CitationEntry;
          onClose: () => void;
        }) {
          const lang = citation.language || inferLanguage(citation.file_path);
          const parsed = parseChunkText(citation.text || '');
          const hasMeta = parsed.symbols.length > 0 || parsed.signature || parsed.imports.length > 0;
          const maxNum = citation.end_line >= citation.start_line
            ? citation.end_line
            : citation.start_line + Math.max(parsed.code.split('\\n').length - 1, 0);
          const gutterWidth = `${Math.max(String(maxNum).length + 1, 3)}ch`;

          useEffect(() => {
            const prev = document.body.style.overflow;
            document.body.style.overflow = 'hidden';
            function handleKey(e: globalThis.KeyboardEvent) {
              if (e.key === 'Escape') onClose();
            }
            document.addEventListener('keydown', handleKey);
            return () => {
              document.body.style.overflow = prev;
              document.removeEventListener('keydown', handleKey);
            };
          }, [onClose]);

          return (
            <div className="deepdoc-code-modal-overlay" onClick={onClose}>
              <div className="deepdoc-code-modal" onClick={(e) => e.stopPropagation()}>
                <div className="deepdoc-code-modal__header">
                  <div className="deepdoc-code-modal__title">
                    <strong>{citation.file_path}</strong>
                    <span>{formatLines(citation.start_line, citation.end_line)}{lang ? ` · ${lang}` : ''}</span>
                  </div>
                  <button className="deepdoc-code-modal__close" onClick={onClose} aria-label="Close">✕</button>
                </div>

                {hasMeta ? (
                  <div className="deepdoc-code-modal__meta">
                    {parsed.symbols.length > 0 ? (
                      <div className="deepdoc-code-modal__meta-row">
                        <span className="deepdoc-code-modal__meta-label">Symbols</span>
                        <span className="deepdoc-code-modal__meta-tags">
                          {parsed.symbols.map(s => <span key={s} className="deepdoc-code-modal__tag">{s}</span>)}
                        </span>
                      </div>
                    ) : null}
                    {parsed.signature ? (
                      <div className="deepdoc-code-modal__meta-row">
                        <span className="deepdoc-code-modal__meta-label">Signature</span>
                        <code className="deepdoc-code-modal__sig">{parsed.signature}</code>
                      </div>
                    ) : null}
                    {parsed.imports.length > 0 ? (
                      <div className="deepdoc-code-modal__meta-row">
                        <span className="deepdoc-code-modal__meta-label">Imports</span>
                        <span className="deepdoc-code-modal__meta-tags">
                          {parsed.imports.map(s => <span key={s} className="deepdoc-code-modal__tag deepdoc-code-modal__tag--dim">{s}</span>)}
                        </span>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div className="deepdoc-code-modal__body">
                  <HighlightedCodeBlock
                    code={parsed.code}
                    language={lang}
                    className="deepdoc-code-modal__syntax"
                    showLineNumbers
                    startingLineNumber={citation.start_line}
                    lineNumberMinWidth={gutterWidth}
                    padding="0 1rem"
                  />
                </div>
              </div>
            </div>
          );
        }

        function ChatbotLoadingSkeleton() {
          return (
            <>
              <div className="deepdoc-chatbot-skeleton">
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--sm" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--full" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--lg" />
                <div className="deepdoc-chatbot-skeleton__block" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--full" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--lg" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--md" />
              </div>
            </>
          );
        }

        function ChatbotSidebarSkeleton() {
          return (
            <div className="deepdoc-chatbot-skeleton">
              <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--md" />
              <div className="deepdoc-chatbot-skeleton__cards">
                <div className="deepdoc-chatbot-skeleton__card" />
                <div className="deepdoc-chatbot-skeleton__card" />
                <div className="deepdoc-chatbot-skeleton__card" />
              </div>
              <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--sm" />
            </div>
          );
        }

        export function ChatbotPanel() {
          const router = useRouter();
          const searchParams = useSearchParams();
          const question = searchParams.get('q')?.trim() ?? '';
          const from = searchParams.get('from')?.trim() || '/';
          const modeParamRaw = searchParams.get('mode');
          const modeParam: 'fast' | 'deep' | 'code' = modeParamRaw === 'deep' ? 'deep' : modeParamRaw === 'code' ? 'code' : 'fast';
          const [draft, setDraft] = useState('');
          const [mode, setMode] = useState<'fast' | 'deep' | 'code'>(modeParam);
          const [activeQuestion, setActiveQuestion] = useState(question);
          const [loading, setLoading] = useState(false);
          const [error, setError] = useState('');
          const [response, setResponse] = useState<ChatResponse | null>(null);
          const [history, setHistory] = useState<ChatHistoryItem[]>([]);
          const [loadedQuestion, setLoadedQuestion] = useState('');
          const [loadedMode, setLoadedMode] = useState<'fast' | 'deep' | 'code'>('fast');
          const [liveTrace, setLiveTrace] = useState<TraceEntry[]>([]);
          const [streamingAnswer, setStreamingAnswer] = useState('');
          const [modalCitation, setModalCitation] = useState<CitationEntry | null>(null);
          const [isDockVisible, setIsDockVisible] = useState(true);
          const latestRequestIdRef = useRef(0);
          const lastScrollYRef = useRef(0);

          useEffect(() => {
            setMode(modeParam);
          }, [modeParam]);

          useEffect(() => {
            if (typeof window === 'undefined') return;

            lastScrollYRef.current = window.scrollY;

            let ticking = false;
            const threshold = 18;

            const syncVisibility = () => {
              ticking = false;
              const nextY = window.scrollY;

              const delta = nextY - lastScrollYRef.current;
              if (Math.abs(delta) < threshold) return;

              if (nextY < 24) {
                setIsDockVisible(true);
                lastScrollYRef.current = nextY;
                return;
              }

              setIsDockVisible(delta < 0);
              lastScrollYRef.current = nextY;
            };

            const onScroll = () => {
              if (ticking) return;
              ticking = true;
              window.requestAnimationFrame(syncVisibility);
            };

            window.addEventListener('scroll', onScroll, { passive: true });

            return () => {
              window.removeEventListener('scroll', onScroll);
            };
          }, []);

          useEffect(() => {
            if (!question) {
              latestRequestIdRef.current += 1;
              setActiveQuestion('');
              setLoading(false);
              setError('');
              setResponse(null);
              setHistory([]);
              setLoadedQuestion('');
              setLiveTrace([]);
              return;
            }
            if (question === loadedQuestion && modeParam === loadedMode) return;
            void askQuestion(question, [], modeParam);
          }, [question, loadedQuestion, modeParam, loadedMode]);

          async function askQuestion(
            nextQuestion: string,
            nextHistory: ChatHistoryItem[],
            nextMode: 'fast' | 'deep' | 'code',
          ) {
            if (!nextQuestion.trim()) return;
            if (!chatbotConfig.apiBaseUrl) {
              setResponse(null);
              setError('Chatbot backend URL is not configured.');
              setLoading(false);
              return;
            }
            const requestId = latestRequestIdRef.current + 1;
            latestRequestIdRef.current = requestId;
            setLoadedQuestion(nextQuestion);
            setLoadedMode(nextMode);
            setLoading(true);
            setError('');
            setResponse(null);
            setLiveTrace([]);
            setStreamingAnswer('');
            try {
              if (nextMode === 'code') {
                const streamRes = await fetch(`${chatbotConfig.apiBaseUrl}/code-deep/stream`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    question: nextQuestion,
                    history: nextHistory,
                    max_rounds: 4,
                  }),
                });

                if (!streamRes.ok || !streamRes.body) {
                  const fallbackRes = await fetch(`${chatbotConfig.apiBaseUrl}/code-deep`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      question: nextQuestion,
                      history: nextHistory,
                      max_rounds: 4,
                    }),
                  });
                  if (!fallbackRes.ok) {
                    throw new Error(`Request failed with ${fallbackRes.status}`);
                  }
                  const fallbackData = (await fallbackRes.json()) as ChatResponse;
                  if (latestRequestIdRef.current != requestId) return;
                  setActiveQuestion(nextQuestion);
                  setMode(nextMode);
                  setResponse(fallbackData);
                  setLiveTrace([]);
                  setHistory([
                    ...nextHistory,
                    { role: 'user', content: nextQuestion },
                    { role: 'assistant', content: fallbackData.answer },
                  ]);
                  return;
                }

                const reader = streamRes.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let streamResult: ChatResponse | null = null;

                while (true) {
                  if (latestRequestIdRef.current != requestId) {
                    return;
                  }
                  const { done, value } = await reader.read();
                  if (done) break;
                  buffer += decoder.decode(value, { stream: true });
                  const parsed = parseSseChunk(buffer);
                  buffer = parsed.remainder;
                  for (const ev of parsed.events) {
                    if (ev.event === 'trace') {
                      try {
                        const payload = JSON.parse(ev.data) as TraceEntry;
                        setLiveTrace(prev => [...prev, payload]);
                      } catch {
                        // ignore malformed trace frame
                      }
                    } else if (ev.event === 'result') {
                      streamResult = JSON.parse(ev.data) as ChatResponse;
                    } else if (ev.event === 'error') {
                      const payload = JSON.parse(ev.data) as { detail?: string };
                      throw new Error(payload.detail || 'Code-aware research failed');
                    }
                  }
                }

                if (!streamResult) {
                  throw new Error('Code-aware stream ended without a result');
                }
                if (latestRequestIdRef.current != requestId) {
                  return;
                }
                setActiveQuestion(nextQuestion);
                setMode(nextMode);
                setResponse(streamResult);
                setLiveTrace([]);
                setHistory([
                  ...nextHistory,
                  { role: 'user', content: nextQuestion },
                  { role: 'assistant', content: streamResult.answer },
                ]);
                return;
              }

              const streamEndpoint = nextMode === 'deep' ? '/deep-research/stream' : '/query/stream';
              const streamRes = await fetch(`${chatbotConfig.apiBaseUrl}${streamEndpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  question: nextQuestion,
                  history: nextHistory,
                  max_rounds: nextMode === 'deep' ? 3 : undefined,
                }),
              });

              if (!streamRes.ok || !streamRes.body) {
                const fallbackEndpoint = nextMode === 'deep' ? '/deep-research' : '/query';
                const fallbackRes = await fetch(`${chatbotConfig.apiBaseUrl}${fallbackEndpoint}`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    question: nextQuestion,
                    history: nextHistory,
                    max_rounds: nextMode === 'deep' ? 3 : undefined,
                  }),
                });
                if (!fallbackRes.ok) {
                  throw new Error(`Request failed with ${fallbackRes.status}`);
                }
                const fallbackData = (await fallbackRes.json()) as ChatResponse;
                if (latestRequestIdRef.current != requestId) return;
                setActiveQuestion(nextQuestion);
                setMode(nextMode);
                setResponse(fallbackData);
                setHistory([
                  ...nextHistory,
                  { role: 'user', content: nextQuestion },
                  { role: 'assistant', content: fallbackData.answer },
                ]);
                return;
              }

              const reader = streamRes.body.getReader();
              const decoder = new TextDecoder();
              let buffer = '';
              let streamResult: ChatResponse | null = null;

              while (true) {
                if (latestRequestIdRef.current != requestId) return;
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const parsed = parseSseChunk(buffer);
                buffer = parsed.remainder;
                for (const ev of parsed.events) {
                  if (ev.event === 'token') {
                    try {
                      const payload = JSON.parse(ev.data) as { text: string };
                      setStreamingAnswer(prev => prev + payload.text);
                    } catch { /* ignore malformed token */ }
                  } else if (ev.event === 'result') {
                    streamResult = JSON.parse(ev.data) as ChatResponse;
                  } else if (ev.event === 'error') {
                    const payload = JSON.parse(ev.data) as { detail?: string };
                    throw new Error(payload.detail || 'Request failed');
                  }
                }
              }

              if (!streamResult) {
                throw new Error('Stream ended without a result');
              }
              if (latestRequestIdRef.current != requestId) return;
              setStreamingAnswer('');
              setActiveQuestion(nextQuestion);
              setMode(nextMode);
              setResponse(streamResult);
              setHistory([
                ...nextHistory,
                { role: 'user', content: nextQuestion },
                { role: 'assistant', content: streamResult.answer },
              ]);
            } catch (err) {
              if (latestRequestIdRef.current != requestId) {
                return;
              }
              setLiveTrace([]);
              setError(err instanceof Error ? err.message : 'Chatbot unavailable');
            } finally {
              if (latestRequestIdRef.current == requestId) {
                setLoading(false);
              }
            }
          }

          function submit(event?: FormEvent<HTMLFormElement>) {
            event?.preventDefault();
            const trimmed = draft.trim();
            if (!trimmed) return;
            const nextHistory = activeQuestion && response ? history.slice(-4) : [];
            setDraft('');
            void askQuestion(trimmed, nextHistory, mode);
            startTransition(() => {
              router.replace(buildAskUrl(trimmed, from, mode));
            });
          }

          const evidenceCitations = response ? workspaceCitations(response) : [];
          const referenceItems = response ? referenceLinks(response) : [];
          const diagnostics = response ? diagnosticsMessages(response) : [];

          return (
            <div className="deepdoc-chatbot-page">
              <Link className="deepdoc-chatbot-page__back" href={from}>
                <span aria-hidden="true">←</span>
                <span>Back to docs</span>
              </Link>

              <div className="deepdoc-chatbot-page__grid">
                <section className="deepdoc-chatbot-panel">
                  <div className="deepdoc-chatbot-panel__header">
                    <p className="deepdoc-chatbot-panel__question">
                      {question ? 'Question' : 'Ready when you are'}
                    </p>
                    {question ? (
                      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-fd-foreground">{question}</h2>
                    ) : null}
                  </div>
                  <div className="deepdoc-chatbot-panel__body">
                    {loading && mode === 'code' ? (
                      <div className="deepdoc-chatbot-trace mb-5" role="status" aria-live="polite">
                        {(() => {
                          const progress = traceHeader(liveTrace);
                          return (
                            <>
                              <div className="deepdoc-chatbot-trace__header">
                                <span className="deepdoc-chatbot-trace__dot" aria-hidden="true" />
                                <strong>{progress.title}</strong>
                                <span>{progress.current} / {progress.total}</span>
                              </div>
                              <div className="deepdoc-chatbot-trace__bar" aria-hidden="true">
                                <span style={{ width: `${progress.progressPct}%` }} />
                              </div>
                            </>
                          );
                        })()}
                        <ul className="deepdoc-chatbot-trace__lines">
                          {liveTrace.length ? (
                            liveTrace.map((entry, idx) => (
                              <li key={`${entry.phase}-${idx}`}>{toTraceLine(entry)}</li>
                            ))
                          ) : (
                            <li>Preparing research context</li>
                          )}
                        </ul>
                      </div>
                    ) : null}
                    {loading && streamingAnswer ? (
                      <div className="text-sm">
                        <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-base font-semibold">Answer</h3>
                        <div className="deepdoc-chatbot-answer prose prose-sm max-w-none dark:prose-invert">
                          <ReactMarkdown>{streamingAnswer}</ReactMarkdown>
                        </div>
                      </div>
                    ) : loading ? (
                      <ChatbotLoadingSkeleton />
                    ) : error ? (
                      <div className="deepdoc-chatbot-panel__empty text-red-600">{error}</div>
                    ) : response ? (
                      <div className="text-sm">
                        <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-base font-semibold">Answer</h3>
                        <div className="deepdoc-chatbot-answer prose prose-sm max-w-none dark:prose-invert">
                          <ReactMarkdown
                            components={{
                              pre({ children }) {
                                return <AnswerPre>{children}</AnswerPre>;
                              },
                              a({ href, children }) {
                                const evidenceId = href?.startsWith('#evidence-')
                                  ? href.replace('#evidence-', '')
                                  : '';
                                const citation = evidenceCitations.find((item) => item.evidence_id === evidenceId);
                                if (citation) {
                                  return (
                                    <button
                                      type="button"
                                      className="deepdoc-chatbot-answer__evidence-link"
                                      onClick={() => setModalCitation(citation)}
                                    >
                                      {children}
                                    </button>
                                  );
                                }
                                return <a href={href}>{children}</a>;
                              },
                              code(props) {
                                const { className, children, ...rest } = props;
                                const content = String(children ?? '');
                                const isInline = !className && !content.includes('\\n');
                                if (isInline) {
                                  return (
                                    <code
                                      {...rest}
                                      className="deepdoc-chatbot-answer__inline-code"
                                    >
                                      {children}
                                    </code>
                                  );
                                }
                                return (
                                  <code {...rest} className={className}>
                                    {children}
                                  </code>
                                );
                              },
                            }}
                          >
                            {answerWithEvidenceLinks(response.answer)}
                          </ReactMarkdown>
                        </div>
                      </div>
                    ) : (
                      <div className="deepdoc-chatbot-panel__empty">
                        Ask a question below and this page will turn into a focused answer workspace with citations and related docs.
                      </div>
                    )}
                  </div>
                </section>

                <aside className="deepdoc-chatbot-sidebar">
                  <div className="deepdoc-chatbot-sidebar__header">
                    <h2 className="text-sm font-semibold text-fd-foreground">Supporting context</h2>
                    <p className="mt-2 text-sm text-fd-muted-foreground">
                      Code and docs referenced by the current answer appear here.
                    </p>
                  </div>

                  {loading ? <ChatbotSidebarSkeleton /> : null}

                  {!loading && evidenceCitations.length ? (
                    <div className="mb-5">
                      <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-sm font-semibold">
                        Source evidence
                        <span className="deepdoc-chatbot-section-hint"> — click to view</span>
                      </h3>
                      <ul className="deepdoc-chatbot-citation-list">
                        {evidenceCitations.map((citation) => (
                          <li
                            id={citation.evidence_id ? `evidence-${citation.evidence_id}` : undefined}
                            key={`${citation.evidence_id || citation.file_path}-${citation.start_line}`}
                            className={citation.text ? 'deepdoc-chatbot-citation-list__clickable' : ''}
                            onClick={() => citation.text && setModalCitation(citation)}
                            role={citation.text ? 'button' : undefined}
                            tabIndex={citation.text ? 0 : undefined}
                            onKeyDown={(e) => {
                              if (citation.text && (e.key === 'Enter' || e.key === ' ')) {
                                e.preventDefault();
                                setModalCitation(citation);
                              }
                            }}
                          >
                            <div className="deepdoc-chatbot-citation-list__row">
                              <div className="deepdoc-chatbot-citation-list__text">
                                <strong>{citation.file_path}</strong>
                                <span>{formatLines(citation.start_line, citation.end_line)}</span>
                              </div>
                              {citation.text ? (
                                <span className="deepdoc-chatbot-citation-list__action">Preview</span>
                              ) : null}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {!loading && diagnostics.length ? (
                    <div className="mb-5">
                      <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-sm font-semibold">Diagnostics</h3>
                      <ul className="deepdoc-chatbot-citation-list">
                        {diagnostics.map((message) => (
                          <li key={message}>
                            <span>{message}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {!loading && referenceItems.length ? (
                    <div>
                      <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-sm font-semibold">Read next</h3>
                      <ul className="deepdoc-chatbot-citation-list">
                        {referenceItems.map((link) => (
                          <li key={`${link.doc_path}-${link.url}`}>
                            <strong>{link.title}</strong>
                            <span>{link.doc_path}</span>
                            {link.url && link.url !== '#' ? (
                              <Link className="mt-2 inline-flex text-sm underline" href={link.url}>
                                Open docs
                              </Link>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {!response && !loading ? (
                    <div className="deepdoc-chatbot-panel__empty">
                      Ask a question to populate this sidebar with citations and suggested documentation.
                    </div>
                  ) : null}
                </aside>
              </div>

              {modalCitation ? (
                <CodeModal
                  citation={modalCitation}
                  onClose={() => setModalCitation(null)}
                />
              ) : null}

              <div className={`deepdoc-chatbot-shell ${isDockVisible ? 'deepdoc-chatbot-shell--visible' : 'deepdoc-chatbot-shell--hidden'}`}>
                <form className="deepdoc-chatbot-dock" onSubmit={submit}>
                  <div className="deepdoc-chatbot-dock__meta">
                    <div className="min-w-0">
                      <p className="deepdoc-chatbot-dock__eyebrow">
                        {response ? 'Ask a follow-up question' : 'Ask the codebase'}
                      </p>
                      <p className="text-sm font-medium text-fd-muted-foreground">
                        {response
                          ? 'Stay on this page and keep the answer flow going.'
                          : 'Start with a question about architecture, files, or behavior.'}
                      </p>
                    </div>
                  </div>
                  <div className="mb-3 flex items-center gap-2">
                    <button
                      className={`deepdoc-chatbot-mode-toggle ${mode === 'fast' ? 'deepdoc-chatbot-mode-toggle--active' : ''}`}
                      onClick={() => setMode('fast')}
                      type="button"
                    >
                      Fast
                    </button>
                  <button
                    className={`deepdoc-chatbot-mode-toggle ${mode === 'deep' ? 'deepdoc-chatbot-mode-toggle--active' : ''}`}
                    onClick={() => setMode('deep')}
                    type="button"
                  >
                    Deep Research
                  </button>
                  <button
                    className={`deepdoc-chatbot-mode-toggle ${mode === 'code' ? 'deepdoc-chatbot-mode-toggle--active' : ''}`}
                    onClick={() => setMode('code')}
                    type="button"
                  >
                    Code Aware
                  </button>
                </div>
                  <div className="deepdoc-chatbot-dock__row">
                    <textarea
                      className="deepdoc-chatbot-dock__input text-sm"
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                        if (event.nativeEvent.isComposing) return;
                        if (event.key === 'Enter' && !event.shiftKey) {
                          event.preventDefault();
                          event.currentTarget.form?.requestSubmit();
                        }
                      }}
                      placeholder="Ask a follow-up question"
                      rows={1}
                      value={draft}
                    />
                    <button
                      className="deepdoc-chatbot-dock__submit text-sm font-semibold"
                      disabled={loading}
                      type="submit"
                    >
                      {loading ? 'Thinking...' : 'Ask'}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          );
        }
        """
    )
