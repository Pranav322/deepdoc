import React, { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import {
  Terminal,
  Github,
  Copy,
  CheckCircle2,
  ArrowRight,
  GitMerge,
  ChevronRight,
  FileCode2,
  Search,
  GitCommit,
  Box,
} from "lucide-react";
import { Navbar } from "../components/Navbar";

/* ─── typewriter hook ────────────────────────────────────────────── */
function useTypewriter(lines: string[], startDelay = 0, speed = 28) {
  const [displayed, setDisplayed] = useState<string[]>([]);
  const [currentLine, setCurrentLine] = useState(0);
  const [currentChar, setCurrentChar] = useState(0);
  const [started, setStarted] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setStarted(true), startDelay);
    return () => clearTimeout(t);
  }, [startDelay]);

  useEffect(() => {
    if (!started || currentLine >= lines.length) return;
    const line = lines[currentLine];
    if (currentChar < line.length) {
      const t = setTimeout(() => setCurrentChar(c => c + 1), speed);
      return () => clearTimeout(t);
    } else {
      const t = setTimeout(() => {
        setDisplayed(d => [...d, line]);
        setCurrentLine(l => l + 1);
        setCurrentChar(0);
      }, 100);
      return () => clearTimeout(t);
    }
  }, [started, currentLine, currentChar, lines, speed]);

  const inProgress = currentLine < lines.length
    ? lines[currentLine].slice(0, currentChar)
    : null;

  return { displayed, inProgress };
}

/* ─── chat typewriter ────────────────────────────────────────────── */
const CHAT_RESPONSE = `The auth flow involves three components working in sequence:

1. AuthMiddleware (auth_middleware.py:42) extracts the Bearer
   token from Authorization header and verifies its signature
   using the cached public key.

2. SessionStore (redis_store.py:118) — a Redis-backed store —
   validates the token_id hasn't been revoked. TTL on the Redis
   key mirrors token expiry, so revoked sessions fail here.

3. If both checks pass, a User object is attached to
   request.state for all downstream route handlers.

Key detail: mid-request Redis expiry does NOT interrupt the
current request — validation only runs in middleware.`;

function ChatTypewriter({ trigger }: { trigger: boolean }) {
  const [text, setText] = useState("");
  const [done, setDone] = useState(false);
  const idx = useRef(0);

  useEffect(() => {
    if (!trigger) return;
    idx.current = 0;
    setText("");
    setDone(false);
    const interval = setInterval(() => {
      idx.current += 1;
      setText(CHAT_RESPONSE.slice(0, idx.current));
      if (idx.current >= CHAT_RESPONSE.length) {
        clearInterval(interval);
        setDone(true);
      }
    }, 12);
    return () => clearInterval(interval);
  }, [trigger]);

  return (
    <span>
      {text}
      {!done && <span className="animate-pulse text-[#00E5FF]">▋</span>}
    </span>
  );
}

/* ─── terminal lines ─────────────────────────────────────────────── */
const GEN_LINES = [
  "$ deepdoc generate --path ./src --watch",
  "",
  "⠋ Scanning 42 Python files...",
  "  → Parsing AST and building symbol index",
  "  → Embedding 1,247 code chunks",
  "  → Running generation pipeline",
  "",
  "✓ docs/api/auth.md",
  "✓ docs/api/payments.md",
  "✓ docs/architecture/session-store.md",
  "✓ docs/architecture/middleware.md",
  "  … 18 more files",
  "",
  "✓ Documentation generated in 4.1s",
  "  Watching for changes...",
  "",
  "  ~ src/auth/middleware.py modified",
  "  → Re-evaluating 3 affected files",
  "✓ Docs synced in 0.9s",
];

function lineClass(line: string) {
  if (line.startsWith("✓")) return "text-green-400";
  if (line.startsWith("⠋")) return "text-[#00E5FF]";
  if (line.startsWith("  →")) return "text-gray-500";
  if (line.startsWith("  ~")) return "text-yellow-400";
  if (line.startsWith("$")) return "text-gray-200";
  if (line.startsWith("  …")) return "text-gray-600";
  return "text-gray-600";
}

/* ─── main ───────────────────────────────────────────────────────── */
export function HomePage() {
  const [copied, setCopied] = useState(false);
  const [chatStarted, setChatStarted] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);

  const copyInstall = () => {
    navigator.clipboard.writeText("pip install deepdoc");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  useEffect(() => {
    const el = chatRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) setChatStarted(true); },
      { threshold: 0.3 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const { displayed: genLines, inProgress: genCurrent } = useTypewriter(GEN_LINES, 400, 26);

  const HEADLINE = ["Your", "codebase,", "documented."];

  return (
    <div className="min-h-screen bg-[#050505] text-white font-sans overflow-x-hidden">
      <style dangerouslySetInnerHTML={{__html: `
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        .font-sans { font-family: 'Inter', sans-serif; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        .cyan-text {
          background: linear-gradient(135deg,#00E5FF 0%,#0077FF 100%);
          -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .feature-pill {
          border: 1px solid rgba(255,255,255,0.07);
          background: transparent;
          border-radius: 12px;
          transition: border-color 0.2s;
        }
        .feature-pill:hover { border-color: rgba(0,229,255,0.2); }
        @keyframes slideDown {
          0%   { top: -10%; opacity: 0; }
          20%  { opacity: 1; }
          80%  { opacity: 1; }
          100% { top: 110%; opacity: 0; }
        }
        .line-glow-left  { animation: slideDown 4s ease-in-out infinite; }
        .line-glow-right { animation: slideDown 4s ease-in-out 0.6s infinite; }
        @keyframes slideRight {
          0%   { left: -10%; opacity: 0; }
          20%  { opacity: 1; }
          80%  { opacity: 1; }
          100% { left: 110%; opacity: 0; }
        }
        .line-glow-bottom { animation: slideRight 4s ease-in-out 1.2s infinite; }
      `}} />

      <Navbar />

      {/* ── ACETERNITY HERO ───────────────────────────────────────── */}
      <section className="relative mx-auto flex max-w-7xl flex-col items-center justify-center">

        {/* left border line */}
        <div className="absolute inset-y-0 left-0 h-full w-px bg-neutral-800/60">
          <div
            className="line-glow-left absolute w-px"
            style={{
              height: 160,
              background: "linear-gradient(to bottom, transparent, #00E5FF, transparent)",
            }}
          />
        </div>

        {/* right border line */}
        <div className="absolute inset-y-0 right-0 h-full w-px bg-neutral-800/60">
          <div
            className="line-glow-right absolute w-px"
            style={{
              height: 160,
              background: "linear-gradient(to bottom, transparent, #00E5FF, transparent)",
            }}
          />
        </div>

        {/* bottom border line */}
        <div className="absolute inset-x-0 bottom-0 h-px w-full bg-neutral-800/60">
          <div
            className="line-glow-bottom absolute h-px"
            style={{
              width: 160,
              top: 0,
              background: "linear-gradient(to right, transparent, #00E5FF, transparent)",
            }}
          />
        </div>

        <div className="px-6 py-16 md:py-24 w-full flex flex-col items-center">

          {/* version badge */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="inline-flex items-center gap-2 px-3 py-1 mb-8 rounded-full border border-white/10 bg-white/5 text-xs font-medium text-gray-400"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF] animate-pulse" />
            v1.7.0 — Token streaming now live
          </motion.div>

          {/* headline — word by word */}
          <h1 className="relative z-10 mx-auto max-w-4xl text-center text-4xl font-bold md:text-6xl lg:text-7xl leading-tight tracking-tight text-slate-100 mb-6">
            {HEADLINE.map((word, i) => (
              <motion.span
                key={i}
                initial={{ opacity: 0, filter: "blur(4px)", y: 10 }}
                animate={{ opacity: 1, filter: "blur(0px)", y: 0 }}
                transition={{ duration: 0.35, delay: i * 0.12, ease: "easeOut" }}
                className={`mr-3 inline-block ${word === "documented." ? "cyan-text" : ""}`}
              >
                {word}
              </motion.span>
            ))}
          </h1>

          {/* sub-paragraph */}
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.38 }}
            className="relative z-10 mx-auto max-w-xl text-center text-lg font-normal text-neutral-400 mb-10"
          >
            Point it at any Python project. DeepDoc reads your code, maps dependencies, and keeps documentation perfectly in sync as your codebase evolves.
          </motion.p>

          {/* CTAs */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.52 }}
            className="relative z-10 flex flex-wrap items-center justify-center gap-4"
          >
            <button
              onClick={copyInstall}
              className="flex items-center gap-2.5 w-64 justify-center transform rounded-lg bg-white px-6 py-2.5 font-medium text-black transition-all duration-300 hover:-translate-y-0.5 hover:bg-gray-100"
            >
              <Terminal size={15} className="flex-shrink-0" />
              <code className="font-mono text-sm whitespace-nowrap">pip install deepdoc</code>
              {copied
                ? <CheckCircle2 size={14} className="text-green-600 flex-shrink-0" />
                : <Copy size={13} className="text-gray-500 flex-shrink-0" />}
            </button>

            <a
              href="https://github.com/pranav322/deepdoc"
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-center gap-2 w-60 transform rounded-lg border border-neutral-700 bg-black px-6 py-2.5 font-medium text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-neutral-900"
            >
              <Github size={16} />
              View on GitHub
            </a>
          </motion.div>

          {/* terminal preview card */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.65 }}
            className="relative z-10 mt-16 w-full max-w-4xl rounded-3xl border border-neutral-800 bg-neutral-900 p-3 shadow-2xl"
          >
            <div className="w-full overflow-hidden rounded-2xl border border-neutral-700">
              {/* terminal title bar */}
              <div className="flex items-center gap-2 px-4 py-3 bg-[#111] border-b border-white/5">
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-[#FF5F56]" />
                  <div className="w-3 h-3 rounded-full bg-[#FFBD2E]" />
                  <div className="w-3 h-3 rounded-full bg-[#27C93F]" />
                </div>
                <span className="mx-auto font-mono text-xs text-gray-500">bash</span>
              </div>
              {/* terminal body */}
              <div className="bg-[#0A0A0A] px-6 py-5 font-mono text-sm leading-7 min-h-[340px]">
                {genLines.map((line, i) => (
                  <div key={i} className={lineClass(line)}>
                    {line || <>&nbsp;</>}
                  </div>
                ))}
                {genCurrent !== null && (
                  <div className={lineClass(genCurrent)}>
                    {genCurrent}<span className="animate-pulse text-[#00E5FF]">▋</span>
                  </div>
                )}
              </div>
            </div>
          </motion.div>

        </div>
      </section>

      {/* ── THREE MINIMAL PILLARS ─────────────────────────────────── */}
      <section className="px-6 py-24 relative z-10">
        <div className="max-w-4xl mx-auto grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            {
              badge: "01",
              title: "CLI-first",
              body: "One command to generate. One flag to watch. Drops into any CI pipeline without configuration.",
              code: "deepdoc generate --path ./src",
            },
            {
              badge: "02",
              title: "Grounded retrieval",
              body: "Builds a semantic graph of your codebase. Every claim is anchored to real source — no hallucinations.",
              code: "deepdoc chat --mode deep-research",
            },
            {
              badge: "03",
              title: "Always in sync",
              body: "Daemon mode watches for file changes and re-runs only the affected documentation sections in under a second.",
              code: "deepdoc generate --watch",
            },
          ].map((p, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.5, delay: i * 0.1 }}
              className="feature-pill p-6 flex flex-col gap-4"
            >
              <div className="font-mono text-xs text-gray-600">{p.badge}</div>
              <div>
                <div className="font-semibold text-white mb-1.5">{p.title}</div>
                <div className="text-sm text-gray-500 leading-relaxed">{p.body}</div>
              </div>
              <div className="mt-auto pt-2">
                <code className="font-mono text-xs text-[#00E5FF]/70 bg-[#00E5FF]/5 px-2 py-1 rounded">{p.code}</code>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── PIPELINE ──────────────────────────────────────────────── */}
      <section className="px-6 py-24 border-t border-white/[0.06] bg-[#050505] relative z-10">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <div className="font-mono text-xs text-gray-600 mb-3">HOW IT WORKS</div>
            <h2 className="text-3xl sm:text-4xl font-bold">Pipeline architecture</h2>
          </div>

          <div className="flex flex-col md:flex-row items-center justify-center gap-4 md:gap-0">
            {[
              {
                stage: "01",
                title: "Ingest & Parse",
                content: (
                  <div className="font-mono text-xs leading-6 text-gray-400">
                    <span className="text-purple-400">import</span> ast<br />
                    <span className="text-blue-400">def</span> <span className="text-yellow-300">parse</span>():<br />
                    <span className="text-gray-600">{"  "}# Extract nodes</span><br />
                    <span className="text-white">{"  "}tree = ast.parse(src)</span>
                  </div>
                ),
              },
              {
                stage: "02",
                title: "Semantic Model",
                content: (
                  <div className="flex flex-col gap-2 items-center justify-center h-full">
                    <div className="flex gap-1.5">
                      <div className="w-14 h-3 rounded-sm bg-purple-500/20" />
                      <div className="w-8 h-3 rounded-sm bg-[#00E5FF]/20" />
                      <div className="w-20 h-3 rounded-sm bg-blue-500/20" />
                    </div>
                    <div className="flex gap-1.5">
                      <div className="w-16 h-3 rounded-sm bg-[#00E5FF]/20" />
                      <div className="w-12 h-3 rounded-sm bg-purple-500/20" />
                    </div>
                    <div className="font-mono text-xs text-gray-600 mt-2">[0.12, −0.44, 0.88…]</div>
                  </div>
                ),
              },
              {
                stage: "03",
                title: "Generate Docs",
                content: (
                  <div className="font-sans text-xs leading-6">
                    <div className="font-bold text-white mb-2">Authentication</div>
                    <div className="w-full h-2 bg-gray-800 rounded mb-1.5" />
                    <div className="w-3/4 h-2 bg-gray-800 rounded mb-3" />
                    <div className="w-full h-8 bg-[#111] rounded border border-white/5" />
                  </div>
                ),
              },
            ].map((s, i) => (
              <React.Fragment key={i}>
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.5, delay: i * 0.15 }}
                  className="flex-1 w-full rounded-xl border border-white/[0.07] bg-transparent p-6"
                >
                  <div className="font-mono text-xs text-gray-600 mb-3">{s.stage}</div>
                  <div className="font-semibold text-white mb-4">{s.title}</div>
                  <div className="h-28 bg-white/[0.025] rounded-lg border border-white/[0.06] p-4 flex flex-col justify-center">
                    {s.content}
                  </div>
                </motion.div>
                {i < 2 && (
                  <>
                    <div className="hidden md:flex items-center justify-center w-12 flex-shrink-0">
                      <ArrowRight className="text-[#00E5FF] opacity-60" size={20} />
                    </div>
                    <div className="flex md:hidden items-center justify-center py-1">
                      <ArrowRight className="text-[#00E5FF]/40 rotate-90" size={18} />
                    </div>
                  </>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </section>

      {/* ── VS CODE ───────────────────────────────────────────────── */}
      <section className="px-6 py-24 border-t border-white/[0.06] bg-[#050505] relative z-10">
        <div className="max-w-4xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-14 items-center">
          <motion.div
            initial={{ opacity: 0, x: -24 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.6 }}
          >
            <div className="font-mono text-xs text-gray-600 mb-4">EDITOR INTEGRATION</div>
            <h2 className="text-3xl sm:text-4xl font-bold mb-5">Lives in your editor.</h2>
            <p className="text-gray-400 leading-relaxed mb-8 text-sm">
              The DeepDoc VS Code extension surfaces generated documentation inline as hover tooltips — without leaving your file. Generate docs for a single file, toggle inline views, or open a chat panel for any selection.
            </p>
            <ul className="space-y-3">
              {[
                "Inline doc generation per file",
                "Hover tooltips for any function or class",
                "Open chat for any selection",
              ].map((item, i) => (
                <li key={i} className="flex items-center gap-3 text-sm text-gray-300">
                  <CheckCircle2 size={15} className="text-[#00E5FF] flex-shrink-0" />
                  {item}
                </li>
              ))}
            </ul>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 24 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.6 }}
            className="rounded-xl border border-[#2d2d2d] bg-[#1E1E1E] shadow-2xl overflow-hidden h-[340px] flex"
          >
            <div className="hidden sm:flex w-11 bg-[#333] flex-col items-center py-4 gap-5 border-r border-[#252526]">
              <FileCode2 size={20} className="text-gray-500" />
              <Search size={20} className="text-gray-500" />
              <GitCommit size={20} className="text-gray-500" />
              <Box size={20} className="text-[#00E5FF] drop-shadow-[0_0_8px_rgba(0,229,255,0.7)]" />
            </div>
            <div className="hidden sm:flex w-40 bg-[#252526] border-r border-[#1E1E1E] flex-col flex-shrink-0">
              <div className="text-[9px] text-gray-500 uppercase px-4 py-3 tracking-wider">Explorer</div>
              <div className="px-3 py-1 text-xs text-gray-300 flex items-center gap-1.5 bg-[#37373D]"><ChevronRight size={12}/> src</div>
              <div className="px-5 py-1 text-xs text-gray-500 flex items-center gap-1.5"><FileCode2 size={11}/> main.py</div>
              <div className="px-5 py-1 text-xs text-[#00E5FF] flex items-center gap-1.5 bg-[#00E5FF]/8"><FileCode2 size={11}/> auth.py</div>
              <div className="px-5 py-1 text-xs text-gray-500 flex items-center gap-1.5"><FileCode2 size={11}/> utils.py</div>
            </div>
            <div className="flex-1 bg-[#1E1E1E] flex flex-col relative overflow-hidden">
              <div className="flex bg-[#2D2D2D] border-b border-[#1e1e1e]">
                <div className="px-4 py-2 bg-[#1E1E1E] text-xs text-[#00E5FF] border-t-2 border-[#00E5FF] flex items-center gap-1.5">
                  <FileCode2 size={11}/> auth.py
                </div>
              </div>
              <div className="p-4 font-mono text-xs flex overflow-hidden">
                <div className="text-gray-600 mr-4 select-none leading-6">12<br/>13<br/>14<br/>15<br/>16</div>
                <div className="text-gray-400 leading-6">
                  <span className="text-purple-400">@router.post</span>(<span className="text-yellow-300">"/login"</span>)<br/>
                  <span className="text-blue-400">async def</span> <span className="text-yellow-200">login</span>(data):<br/>
                  <span className="text-gray-600">{"    "}user = authenticate_user(data)</span><br/>
                  <span className="text-gray-600">{"    "}if not user:</span><br/>
                  <span className="text-gray-600">{"        "}raise HTTPException(400)</span>
                </div>
              </div>
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 1, duration: 0.4 }}
                className="absolute top-[80px] left-[100px] bg-[#252526] border border-[#444] rounded-lg shadow-2xl w-[220px] z-20 overflow-hidden"
              >
                <div className="bg-[#2d2d2d] px-3 py-2 flex items-center gap-2 border-b border-[#444]">
                  <Box size={11} className="text-[#00E5FF]" />
                  <span className="text-xs font-semibold text-gray-200">DeepDoc</span>
                </div>
                <div className="p-3 text-xs text-gray-400 font-sans leading-relaxed">
                  <span className="text-white font-medium">login()</span> — OAuth2 password flow.<br/>
                  <span className="text-gray-500">Calls authenticate_user, returns JWT. Raises 400 on bad credentials.</span>
                </div>
              </motion.div>
              <div className="absolute bottom-0 w-full h-5 bg-[#007ACC] flex items-center px-3 text-[9px] text-white justify-between">
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-1"><GitMerge size={10}/> main</span>
                  <span>Python 3.10</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Box size={10}/> DeepDoc Ready
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── CHAT DEMO ─────────────────────────────────────────────── */}
      <section
        ref={chatRef}
        className="px-6 py-24 border-t border-white/5 bg-[#050505] relative z-10"
      >
        <div className="max-w-4xl mx-auto grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-12 items-start">

          <motion.div
            initial={{ opacity: 0, x: -24 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.6 }}
            className="lg:pt-8"
          >
            <div className="font-mono text-xs text-gray-600 mb-4">CHAT MODE</div>
            <h2 className="text-3xl sm:text-4xl font-bold mb-5">Ask your codebase anything.</h2>
            <p className="text-gray-400 leading-relaxed text-sm mb-8">
              Stop grepping. Two modes — fast retrieval for point lookups (~800ms), and deep research for architectural questions that span multiple files (3–8s).
            </p>
            <div className="space-y-3">
              {[
                { mode: "fast", label: "Fast mode", desc: "~800ms · single vector lookup" },
                { mode: "deep", label: "Deep research", desc: "3–8s · multi-hop reasoning" },
              ].map(m => (
                <div key={m.mode} className="flex items-center gap-3 p-3 rounded-lg border border-white/6 bg-white/[0.02]">
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${m.mode === "fast" ? "bg-[#00E5FF]" : "bg-purple-400"}`} />
                  <div>
                    <div className="text-sm font-medium text-white">{m.label}</div>
                    <div className="text-xs text-gray-500 font-mono">{m.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 24 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.6 }}
          >
            <div className="rounded-xl border border-white/8 overflow-hidden shadow-[0_0_60px_rgba(91,33,182,0.12)]">
              <div className="flex items-center gap-2 px-4 py-3 bg-[#0d0d0d] border-b border-white/5">
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-[#FF5F56]" />
                  <div className="w-3 h-3 rounded-full bg-[#FFBD2E]" />
                  <div className="w-3 h-3 rounded-full bg-[#27C93F]" />
                </div>
                <span className="mx-auto font-mono text-xs text-gray-500">deepdoc chat</span>
              </div>
              <div className="bg-[#080808] p-5 font-mono text-xs leading-6 min-h-[380px]">
                <div className="text-gray-500 mb-4">$ deepdoc chat --path ./src --mode deep-research</div>
                <div className="text-[#00E5FF] mb-4">Connected. Using deep-research mode (3–8s).</div>
                <div className="mb-3">
                  <span className="text-purple-400">you</span>
                  <span className="text-gray-600"> › </span>
                  <span className="text-gray-200">How does auth middleware interact with the session store?</span>
                </div>
                <div className="flex items-start gap-2 mb-2">
                  <span className="text-[#00E5FF] flex-shrink-0">ai</span>
                  <span className="text-gray-600 flex-shrink-0"> › </span>
                  <div>
                    {!chatStarted && (
                      <span className="text-gray-600 italic">Analyzing 14 files across 3 directories…</span>
                    )}
                    {chatStarted && (
                      <span className="text-gray-300 whitespace-pre-wrap">
                        <ChatTypewriter trigger={chatStarted} />
                      </span>
                    )}
                  </div>
                </div>
                {chatStarted && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: CHAT_RESPONSE.length * 0.012 + 0.5 }}
                    className="mt-4 pt-4 border-t border-white/5"
                  >
                    <span className="text-purple-400">you</span>
                    <span className="text-gray-600"> › </span>
                    <span className="animate-pulse text-[#00E5FF]">▋</span>
                  </motion.div>
                )}
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── CHANGELOG TEASER ──────────────────────────────────────── */}
      <section className="px-6 py-24 border-t border-white/[0.06] bg-[#050505] relative z-10">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-end justify-between mb-10">
            <div>
              <div className="font-mono text-xs text-gray-600 mb-3">RECENT RELEASES</div>
              <h2 className="text-3xl font-bold">Ship at velocity.</h2>
            </div>
            <a href="/changelog" className="text-sm text-[#00E5FF] hover:text-white transition-colors flex items-center gap-1">
              Full changelog <ArrowRight size={13} />
            </a>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[
              { v: "v1.7.0", date: "May 2026", note: "Token streaming for fast and deep-research modes. Modular v2 pipeline." },
              { v: "v1.6.0", date: "Apr 2026", note: "Evidence-grounded answers, symbol corpus, SQLite FTS retrieval." },
              { v: "v1.5.0", date: "Apr 2026", note: "Scanned runtime endpoint planning. Agent-style research loop." },
            ].map((r, i) => (
              <motion.a
                key={i}
                href="/changelog"
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: i * 0.08 }}
                className="block p-5 rounded-xl border border-white/6 bg-white/[0.02] hover:border-white/12 hover:bg-white/[0.035] transition-all"
              >
                <div className="flex items-center gap-2.5 mb-3">
                  <span className={`font-mono text-xs font-bold ${i === 0 ? "text-[#00E5FF]" : "text-gray-400"}`}>{r.v}</span>
                  {i === 0 && <span className="text-[10px] font-medium text-[#00E5FF] bg-[#00E5FF]/10 border border-[#00E5FF]/20 px-2 py-0.5 rounded-full">latest</span>}
                  <span className="text-xs text-gray-600 ml-auto">{r.date}</span>
                </div>
                <p className="text-xs text-gray-500 leading-relaxed">{r.note}</p>
              </motion.a>
            ))}
          </div>
        </div>
      </section>

      {/* ── FOOTER ────────────────────────────────────────────────── */}
      <footer className="px-6 py-10 border-t border-white/5 bg-[#050505]">
        <div className="max-w-4xl mx-auto flex flex-col md:flex-row items-center justify-between gap-5">
          <span className="font-mono font-bold text-lg text-white">DeepDoc</span>
          <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-gray-600">
            <a href="https://github.com/pranav322/deepdoc" target="_blank" rel="noreferrer" className="hover:text-white transition-colors">GitHub</a>
            <a href="https://pypi.org/project/deepdoc" target="_blank" rel="noreferrer" className="hover:text-white transition-colors">PyPI</a>
            <a href="/docs" className="hover:text-white transition-colors">Docs</a>
            <a href="/changelog" className="hover:text-white transition-colors">Changelog</a>
            <a href="https://github.com/pranav322/deepdoc/blob/main/LICENSE" target="_blank" rel="noreferrer" className="hover:text-white transition-colors">MIT License</a>
          </div>
          <button
            onClick={copyInstall}
            className="group flex items-center gap-2 px-4 py-2 rounded-md bg-[#111] border border-white/8 hover:border-[#00E5FF]/40 transition-all"
          >
            <Terminal size={13} className="text-gray-600" />
            <code className="font-mono text-xs text-gray-400 group-hover:text-white transition-colors">pip install deepdoc</code>
          </button>
        </div>
      </footer>
    </div>
  );
}
