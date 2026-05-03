import React, { useState } from "react";
import { motion } from "framer-motion";
import { 
  Terminal, 
  FileCode2, 
  Search, 
  Zap, 
  Github, 
  Copy,
  CheckCircle2,
  Box,
  Layers,
  Sparkles,
  ChevronRight,
  GitCommit,
  GitMerge,
  ArrowRight,
  Cpu,
  MessageSquare,
  Bot
} from "lucide-react";
import { Navbar } from "./_Navbar";

export function LandingPage() {
  const [copied, setCopied] = useState(false);
  const [chatMode, setChatMode] = useState<"fast" | "deep">("fast");

  const copyInstall = () => {
    navigator.clipboard.writeText("pip install deepdoc");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="min-h-screen bg-[#050505] text-white selection:bg-[#00E5FF] selection:text-black font-sans overflow-x-hidden">
      <style dangerouslySetInnerHTML={{__html: `
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        
        .font-sans { font-family: 'Inter', sans-serif; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        
        .glass-panel {
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid rgba(255, 255, 255, 0.05);
          backdrop-filter: blur(10px);
        }
        
        .cyan-gradient {
          background: linear-gradient(135deg, #00E5FF 0%, #0077FF 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }

        .bg-grid {
          background-size: 40px 40px;
          background-image: linear-gradient(to right, rgba(255, 255, 255, 0.05) 1px, transparent 1px),
                            linear-gradient(to bottom, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
          mask-image: radial-gradient(circle at center, black, transparent 80%);
        }

        @keyframes typewriter {
          from { width: 0; }
          to { width: 100%; }
        }
        @keyframes blink {
          50% { border-color: transparent; }
        }
        .typing-effect {
          overflow: hidden;
          white-space: nowrap;
          border-right: 2px solid #00E5FF;
          animation: typewriter 2s steps(40, end), blink 0.75s step-end infinite;
          max-width: 100%;
        }
        .typing-effect-2 {
          overflow: hidden;
          white-space: nowrap;
          border-right: 2px solid #00E5FF;
          width: 0;
          animation: typewriter 2s steps(40, end) 6s forwards, blink 0.75s step-end infinite;
        }
        
        .flow-line {
          stroke-dasharray: 10;
          animation: flow 2s linear infinite;
        }
        @keyframes flow {
          to { stroke-dashoffset: -20; }
        }
      `}} />

      <Navbar />

      {/* Hero Section */}
      <section className="relative min-h-[90vh] flex items-center justify-center pt-10 pb-20 px-4 sm:px-6 overflow-hidden">
        <div className="absolute inset-0 z-0">
          <div className="absolute inset-0 bg-grid opacity-40"></div>
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[400px] sm:w-[800px] sm:h-[800px] bg-[#00E5FF] opacity-[0.07] rounded-full blur-[120px] pointer-events-none"></div>
        </div>

        <div className="relative z-10 max-w-5xl mx-auto text-center w-full flex flex-col items-center">
          <motion.h1 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="text-4xl sm:text-5xl md:text-7xl font-bold tracking-tight mb-4 sm:mb-6 leading-tight"
          >
            Your codebase, documented. <br />
            <span className="cyan-gradient">Automatically.</span>
          </motion.h1>
          
          <motion.p 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="text-base sm:text-lg md:text-xl text-gray-400 max-w-2xl mb-8 sm:mb-10 px-2"
          >
            DeepDoc keeps your engineering docs in sync as your code evolves. Point it at any Python project. It reads your code, maps dependencies, and generates structured documentation. Every time your code changes, your docs update with it.
          </motion.p>
          
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="flex flex-col sm:flex-row items-center gap-3 sm:gap-4 mb-10 sm:mb-16 w-full max-w-sm sm:max-w-none"
          >
            <button 
              onClick={copyInstall}
              className="group flex items-center justify-between w-full sm:w-[280px] px-4 py-3 rounded-lg bg-[#111] border border-white/10 hover:border-[#00E5FF]/50 transition-all duration-300"
            >
              <div className="flex items-center gap-3">
                <Terminal size={18} className="text-gray-500 flex-shrink-0" />
                <code className="font-mono text-sm text-gray-300 group-hover:text-white transition-colors">pip install deepdoc</code>
              </div>
              {copied ? <CheckCircle2 size={16} className="text-[#00E5FF] flex-shrink-0" /> : <Copy size={16} className="text-gray-500 group-hover:text-white transition-colors flex-shrink-0" />}
            </button>
            <a 
              href="https://github.com/pranav322/deepdoc"
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-center gap-2 w-full sm:w-auto px-6 py-3 rounded-lg bg-white text-black font-medium hover:bg-gray-200 transition-colors"
            >
              <Github size={18} />
              View on GitHub
            </a>
          </motion.div>

          {/* Animated Terminal */}
          <motion.div 
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="w-full max-w-3xl rounded-xl border border-white/10 bg-[#0A0A0A] shadow-2xl overflow-hidden text-left"
          >
            <div className="flex items-center px-4 py-3 border-b border-white/5 bg-[#111]">
              <div className="flex gap-2">
                <div className="w-3 h-3 rounded-full bg-[#FF5F56]"></div>
                <div className="w-3 h-3 rounded-full bg-[#FFBD2E]"></div>
                <div className="w-3 h-3 rounded-full bg-[#27C93F]"></div>
              </div>
              <div className="mx-auto text-xs text-gray-500 font-mono">bash — deepdoc</div>
            </div>
            <div className="p-4 sm:p-6 font-mono text-xs sm:text-sm leading-relaxed text-gray-300 overflow-x-auto">
              <div className="flex items-baseline text-gray-500 mb-2 min-w-0">
                <span className="text-[#00E5FF] mr-2 flex-shrink-0">➜</span>
                <span className="flex-shrink-0">~/project</span>
                <div className="typing-effect text-white ml-2">deepdoc generate --watch</div>
              </div>
              <motion.div 
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 2 }}
              >
                <div className="text-[#00E5FF] mt-4 mb-1">⠋ Initializing architecture map...</div>
                <div className="text-gray-500 mb-1">Found 42 Python files, 12 endpoints</div>
                <div className="text-green-400 mt-2">✓ Documentation generated successfully!</div>
                <div className="text-gray-400 mt-2 mb-4">Watching for changes...</div>
              </motion.div>
              
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 5.5 }}
              >
                <div className="text-yellow-400 mb-1">File modified: src/auth/middleware.py</div>
                <div className="text-[#00E5FF] mb-1">⠋ Re-evaluating dependencies...</div>
                <div className="text-gray-500 mb-1">Updating Auth flow docs, Session docs</div>
                <div className="text-green-400 mt-2">✓ Docs synced in 1.2s</div>
              </motion.div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="py-16 sm:py-24 px-4 sm:px-6 relative z-10 bg-gradient-to-b from-[#050505] to-[#0A0A15]">
        <div className="max-w-6xl mx-auto">
          <div className="mb-10 sm:mb-16 text-left sm:text-center">
            <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold mb-3 sm:mb-4">Engineered for precision.</h2>
            <p className="text-gray-400 max-w-2xl sm:mx-auto text-sm sm:text-base">
              DeepDoc isn't just a wrapper around an LLM. It's a structured pipeline that reads your code, 
              understands dependencies, and outputs accurate, grounded documentation.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 sm:gap-6">
            {/* Feature 1 */}
            <motion.div 
              whileHover={{ scale: 1.02 }}
              className="p-6 sm:p-8 rounded-2xl glass-panel group transition-all duration-300 border border-white/5 hover:border-[#00E5FF]/30 hover:shadow-[0_0_30px_rgba(0,229,255,0.1)] overflow-hidden relative"
            >
              <h3 className="text-lg sm:text-xl font-bold mb-2 sm:mb-3 flex items-center gap-2"><Zap className="text-[#00E5FF]" size={20}/> Auto-updating Docs</h3>
              <p className="text-gray-400 text-sm mb-5 sm:mb-6">Runs as a daemon to keep your markdown files perfectly aligned with the latest commits.</p>
              <div className="rounded-lg bg-[#0A0A0A] border border-white/10 p-4 font-mono text-xs">
                <div className="text-gray-500 line-through">- def verify_token(token: str):</div>
                <div className="text-green-400">+ def verify_token(token: str, strict: bool = True):</div>
                <div className="my-2 border-t border-white/10"></div>
                <div className="text-gray-500 line-through">- Verifies a JWT token.</div>
                <div className="text-green-400">+ Verifies a JWT. If strict is True, checks revocation list.</div>
              </div>
            </motion.div>

            {/* Feature 2 */}
            <motion.div 
              whileHover={{ scale: 1.02 }}
              className="p-6 sm:p-8 rounded-2xl glass-panel group transition-all duration-300 border border-white/5 hover:border-[#00E5FF]/30 hover:shadow-[0_0_30px_rgba(0,229,255,0.1)] overflow-hidden relative"
            >
              <h3 className="text-lg sm:text-xl font-bold mb-2 sm:mb-3 flex items-center gap-2"><Search className="text-[#00E5FF]" size={20}/> Grounded Retrieval</h3>
              <p className="text-gray-400 text-sm mb-5 sm:mb-6">No hallucinations. We build a semantic graph of your codebase to anchor every generated claim.</p>
              <div className="h-[100px] sm:h-[120px] rounded-lg bg-[#0A0A0A] border border-white/10 p-4 flex items-center justify-center relative overflow-hidden">
                <div className="w-10 h-10 rounded-full bg-blue-500/20 border border-blue-500/50 absolute left-10 flex items-center justify-center"><Box size={16} className="text-blue-400"/></div>
                <div className="w-10 h-10 rounded-full bg-purple-500/20 border border-purple-500/50 absolute right-10 flex items-center justify-center"><FileCode2 size={16} className="text-purple-400"/></div>
                <div className="w-12 h-12 rounded-full bg-[#00E5FF]/20 border border-[#00E5FF]/50 z-10 flex items-center justify-center shadow-[0_0_20px_rgba(0,229,255,0.4)]"><Bot size={20} className="text-[#00E5FF]"/></div>
                <svg className="absolute inset-0 w-full h-full pointer-events-none">
                  <path d="M 60 60 L 160 60 L 260 60" stroke="rgba(0, 229, 255, 0.4)" strokeWidth="2" fill="none" className="flow-line" />
                </svg>
              </div>
            </motion.div>

            {/* Feature 3 */}
            <motion.div 
              whileHover={{ scale: 1.02 }}
              className="p-6 sm:p-8 rounded-2xl glass-panel group transition-all duration-300 border border-white/5 hover:border-[#00E5FF]/30 hover:shadow-[0_0_30px_rgba(0,229,255,0.1)] overflow-hidden relative"
            >
              <h3 className="text-lg sm:text-xl font-bold mb-2 sm:mb-3 flex items-center gap-2"><Terminal className="text-[#00E5FF]" size={20}/> CLI-first</h3>
              <p className="text-gray-400 text-sm mb-5 sm:mb-6">Built for terminal power users. Fast, configurable, and easy to integrate into CI/CD pipelines.</p>
              <div className="rounded-lg bg-[#0A0A0A] border border-white/10 p-4 font-mono text-xs text-gray-300">
                <div className="mb-1"><span className="text-pink-400">deepdoc</span> generate \</div>
                <div className="mb-1">  --path <span className="text-yellow-300">./src</span> \</div>
                <div className="mb-1">  --format <span className="text-yellow-300">markdown</span> \</div>
                <div className="mb-1">  --depth <span className="text-yellow-300">full</span></div>
              </div>
            </motion.div>

            {/* Feature 4 */}
            <motion.div 
              whileHover={{ scale: 1.02 }}
              className="p-6 sm:p-8 rounded-2xl glass-panel group transition-all duration-300 border border-white/5 hover:border-[#00E5FF]/30 hover:shadow-[0_0_30px_rgba(0,229,255,0.1)] overflow-hidden relative"
            >
              <h3 className="text-lg sm:text-xl font-bold mb-2 sm:mb-3 flex items-center gap-2"><Layers className="text-[#00E5FF]" size={20}/> VS Code Native</h3>
              <p className="text-gray-400 text-sm mb-5 sm:mb-6">Read generated documentation as hover tooltips directly in your editor while you code.</p>
              <div className="rounded-lg bg-[#1E1E1E] border border-white/10 p-4 font-mono text-xs overflow-hidden relative">
                <div className="flex">
                  <div className="text-gray-600 mr-4 select-none text-right">
                    1<br/>2<br/>3
                  </div>
                  <div>
                    <span className="text-blue-400">def</span> <span className="text-yellow-200">process_payment</span>(amount):<br/>
                    <span className="text-gray-500">  pass</span>
                  </div>
                </div>
                <div className="absolute top-8 left-16 bg-[#252526] border border-white/10 p-3 rounded shadow-xl max-w-[200px] z-10">
                  <div className="font-sans text-xs text-gray-300 mb-1 font-semibold text-[#00E5FF]">DeepDoc Insight</div>
                  <div className="font-sans text-xs text-gray-400 leading-relaxed">Handles Stripe integration. Throws PaymentError on failure.</div>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* Pipeline Section */}
      <section className="py-16 sm:py-24 px-4 sm:px-6 border-y border-white/5 bg-gradient-to-b from-[#0A0A15] to-[#050510] relative z-10">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold mb-10 sm:mb-16 text-center">Pipeline architecture</h2>
          
          <div className="flex flex-col md:flex-row items-center justify-center gap-5 sm:gap-8 relative">
            
            {/* Stage 1 */}
            <div className="flex-1 w-full glass-panel rounded-2xl p-5 sm:p-6 relative border border-white/5 z-10">
              <div className="text-xs sm:text-sm font-bold text-gray-500 mb-3 sm:mb-4 uppercase tracking-wider">STAGE 1</div>
              <h3 className="text-lg sm:text-xl font-bold mb-2 text-white">Ingest & Parse</h3>
              <div className="h-28 sm:h-32 bg-[#050505] rounded-lg mt-3 sm:mt-4 p-4 font-mono text-xs border border-white/5 overflow-hidden">
                <span className="text-purple-400">import</span> ast<br/>
                <span className="text-blue-400">def</span> <span className="text-yellow-200">parse</span>():<br/>
                <span className="text-gray-500 ml-4"># Extracting nodes</span><br/>
                <span className="text-white ml-4">tree = ast.parse(src)</span>
              </div>
            </div>

            <div className="hidden md:flex items-center justify-center px-4 z-0">
              <ArrowRight className="text-[#00E5FF] animate-pulse" size={32} />
            </div>
            <div className="flex md:hidden items-center justify-center py-1 z-0">
              <ArrowRight className="text-[#00E5FF]/50 rotate-90" size={24} />
            </div>

            {/* Stage 2 */}
            <div className="flex-1 w-full glass-panel rounded-2xl p-5 sm:p-6 relative border border-white/5 z-10">
              <div className="text-xs sm:text-sm font-bold text-gray-500 mb-3 sm:mb-4 uppercase tracking-wider">STAGE 2</div>
              <h3 className="text-lg sm:text-xl font-bold mb-2 text-white">Semantic Model</h3>
              <div className="h-28 sm:h-32 bg-[#050505] rounded-lg mt-3 sm:mt-4 p-4 border border-white/5 overflow-hidden flex flex-col justify-center items-center">
                <div className="flex gap-2 mb-2">
                  <div className="w-16 h-4 bg-purple-500/20 rounded"></div>
                  <div className="w-8 h-4 bg-[#00E5FF]/20 rounded"></div>
                  <div className="w-24 h-4 bg-blue-500/20 rounded"></div>
                </div>
                <div className="flex gap-2">
                  <div className="w-20 h-4 bg-[#00E5FF]/20 rounded"></div>
                  <div className="w-16 h-4 bg-purple-500/20 rounded"></div>
                </div>
                <div className="text-xs text-gray-500 mt-4 font-mono">Vector embeddings [0.12, -0.44...]</div>
              </div>
            </div>

            <div className="hidden md:flex items-center justify-center px-4 z-0">
              <ArrowRight className="text-[#00E5FF] animate-pulse" size={32} />
            </div>
            <div className="flex md:hidden items-center justify-center py-1 z-0">
              <ArrowRight className="text-[#00E5FF]/50 rotate-90" size={24} />
            </div>

            {/* Stage 3 */}
            <div className="flex-1 w-full glass-panel rounded-2xl p-5 sm:p-6 relative border border-white/5 z-10">
              <div className="text-xs sm:text-sm font-bold text-gray-500 mb-3 sm:mb-4 uppercase tracking-wider">STAGE 3</div>
              <h3 className="text-lg sm:text-xl font-bold mb-2 text-white">Generate Docs</h3>
              <div className="h-28 sm:h-32 bg-[#050505] rounded-lg mt-3 sm:mt-4 p-4 border border-white/5 overflow-hidden font-sans">
                <div className="text-lg font-bold text-white mb-2">Authentication</div>
                <div className="w-full h-2 bg-gray-800 rounded mb-2"></div>
                <div className="w-3/4 h-2 bg-gray-800 rounded mb-4"></div>
                <div className="w-full h-12 bg-[#111] rounded border border-white/10"></div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* VS Code Extension Section */}
      <section className="py-20 sm:py-32 px-4 sm:px-6 relative z-10">
        <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-10 sm:gap-16 items-center">
          
          <motion.div 
            initial={{ opacity: 0, x: -30 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.6 }}
          >
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 text-sm mb-5 sm:mb-6">
              <Layers size={14} /> VS Code Extension
            </div>
            <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold mb-4 sm:mb-6">Lives in your editor.</h2>
            <p className="text-gray-400 mb-6 sm:mb-8 leading-relaxed text-sm sm:text-base">
              Why leave your IDE to read the docs? The DeepDoc VS Code extension brings our powerful generation 
              and retrieval directly into your workspace. Highlight a complex function, hit a hotkey, and get an 
              instant explanation.
            </p>
            <ul className="space-y-3 sm:space-y-4">
              {[
                "Inline doc generation for specific files",
                "Hover-over explanations for legacy code",
                "Seamless integration with your editor theme"
              ].map((item, i) => (
                <li key={i} className="flex items-start sm:items-center gap-3 text-gray-300 text-sm sm:text-base">
                  <CheckCircle2 size={18} className="text-[#00E5FF] flex-shrink-0 mt-0.5 sm:mt-0" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </motion.div>

          <motion.div 
            initial={{ opacity: 0, x: 30 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.6 }}
            className="rounded-xl border border-[#333] bg-[#1E1E1E] shadow-2xl overflow-hidden flex flex-col sm:flex-row h-auto sm:h-[400px] mt-8 lg:mt-0"
          >
            {/* VS Code Sidebar */}
            <div className="hidden sm:flex w-12 bg-[#333333] flex-col items-center py-4 gap-6 border-r border-[#252526]">
              <FileCode2 size={24} className="text-gray-400"/>
              <Search size={24} className="text-gray-400"/>
              <GitCommit size={24} className="text-gray-400"/>
              <div className="relative group cursor-pointer">
                <Box size={24} className="text-[#00E5FF] drop-shadow-[0_0_8px_rgba(0,229,255,0.8)]"/>
                <div className="absolute left-10 top-0 bg-black text-xs px-2 py-1 rounded border border-white/10 hidden group-hover:block whitespace-nowrap z-50">DeepDoc</div>
              </div>
            </div>
            {/* File Tree */}
            <div className="hidden sm:flex w-48 bg-[#252526] border-r border-[#1E1E1E] flex-col">
              <div className="text-[10px] text-gray-400 uppercase p-4 tracking-wider">Explorer</div>
              <div className="px-4 py-1 text-sm text-gray-300 flex items-center gap-2 bg-[#37373D]"><ChevronRight size={14}/> src</div>
              <div className="px-8 py-1 text-sm text-gray-400 flex items-center gap-2"><FileCode2 size={14}/> main.py</div>
              <div className="px-8 py-1 text-sm text-gray-400 flex items-center gap-2 text-[#00E5FF] bg-[#00E5FF]/10"><FileCode2 size={14}/> auth.py</div>
              <div className="px-8 py-1 text-sm text-gray-400 flex items-center gap-2"><FileCode2 size={14}/> utils.py</div>
            </div>
            {/* Editor Area */}
            <div className="flex-1 bg-[#1E1E1E] flex flex-col relative min-h-[280px] sm:min-h-0">
              <div className="flex bg-[#2D2D2D]">
                <div className="px-4 py-2 bg-[#1E1E1E] text-sm text-[#00E5FF] border-t-2 border-[#00E5FF] flex items-center gap-2">
                  <FileCode2 size={14}/> auth.py
                </div>
              </div>
              <div className="p-4 font-mono text-xs sm:text-sm overflow-hidden flex">
                <div className="text-gray-600 mr-4 select-none text-right">
                  12<br/>13<br/>14<br/>15<br/>16
                </div>
                <div>
                  <span className="text-purple-400">@router.post</span>(<span className="text-yellow-300">"/login"</span>)<br/>
                  <span className="text-blue-400">async def</span> <span className="text-yellow-200">login</span>(form_data: OAuth2PasswordRequestForm):<br/>
                  <span className="text-gray-500">    user = authenticate_user(form_data.username, form_data.password)</span><br/>
                  <span className="text-gray-500">    if not user:</span><br/>
                  <span className="text-gray-500">        raise HTTPException(status_code=400)</span>
                </div>
              </div>
              
              {/* Tooltip Overlay */}
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 1, duration: 0.4 }}
                className="absolute top-24 sm:top-32 left-8 sm:left-16 bg-[#252526] border border-[#444] rounded-lg shadow-2xl w-[240px] sm:w-[300px] z-20 overflow-hidden"
              >
                <div className="bg-[#333] px-3 py-2 flex items-center gap-2 border-b border-[#444]">
                  <Box size={14} className="text-[#00E5FF]" />
                  <span className="text-xs font-semibold text-gray-200">DeepDoc Documentation</span>
                </div>
                <div className="p-3 text-xs text-gray-300 font-sans leading-relaxed">
                  <p className="mb-2"><strong className="text-white">login()</strong> handles OAuth2 password flow.</p>
                  <p className="text-gray-400">Calls <code className="bg-[#111] px-1 rounded">authenticate_user</code>. If successful, generates a JWT session token. Raises 400 on invalid credentials.</p>
                </div>
              </motion.div>

              {/* Status bar */}
              <div className="absolute bottom-0 w-full h-6 bg-[#007ACC] flex items-center px-3 text-[10px] text-white justify-between z-10">
                <div className="flex items-center gap-4">
                  <span className="flex items-center gap-1"><GitMerge size={12}/> main</span>
                  <span>Python 3.10.0</span>
                </div>
                <div className="flex items-center gap-2">
                  <Box size={12}/> <span>DeepDoc Ready</span>
                </div>
              </div>
            </div>
          </motion.div>

        </div>
      </section>

      {/* Chatbot / Deep-Research Section */}
      <section className="py-20 sm:py-32 px-4 sm:px-6 relative z-10 bg-gradient-to-b from-[#050510] to-[#1a0b2e]">
        <div className="absolute inset-0 bg-grid opacity-20 pointer-events-none"></div>
        <div className="max-w-4xl mx-auto text-center mb-10 sm:mb-16 relative z-10">
          <h2 className="text-2xl sm:text-3xl md:text-5xl font-bold mb-4 sm:mb-6">Ask your codebase anything.</h2>
          <p className="text-base sm:text-xl text-gray-400">
            Stop grepping through thousands of files. Chat with your repository using context-aware AI.
          </p>
        </div>

        <div className="max-w-3xl mx-auto glass-panel rounded-2xl overflow-hidden border border-white/10 shadow-2xl relative z-10 bg-[#0A0A0A]/90">
          {/* Chat Header */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between p-4 border-b border-white/5 bg-[#111] gap-3 sm:gap-0">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#00E5FF] to-purple-600 flex items-center justify-center">
                <MessageSquare size={16} className="text-white" />
              </div>
              <div className="font-semibold">DeepDoc Chat</div>
            </div>
            <div className="flex bg-[#050505] rounded-lg p-1 border border-white/5 w-full sm:w-auto">
              <button 
                onClick={() => setChatMode("fast")}
                className={`flex-1 sm:flex-none px-3 sm:px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${chatMode === 'fast' ? 'bg-[#222] text-white shadow' : 'text-gray-500 hover:text-gray-300'}`}
              >
                Fast Mode (~800ms)
              </button>
              <button 
                onClick={() => setChatMode("deep")}
                className={`flex-1 sm:flex-none px-3 sm:px-4 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center justify-center gap-1 ${chatMode === 'deep' ? 'bg-purple-600/20 text-purple-300 border border-purple-500/30' : 'text-gray-500 hover:text-gray-300'}`}
              >
                <Sparkles size={12} /> Deep Research (~5s)
              </button>
            </div>
          </div>

          {/* Chat Body */}
          <div className="p-4 sm:p-6 space-y-5 sm:space-y-6 h-[320px] sm:h-[400px] overflow-y-auto">
            {/* User Message */}
            <div className="flex justify-end">
              <div className="bg-[#222] text-white px-4 py-3 rounded-2xl rounded-tr-sm max-w-[85%] text-xs sm:text-sm">
                How does the auth middleware interact with the session store?
              </div>
            </div>

            {/* AI Message */}
            <div className="flex justify-start">
              <div className="flex gap-2 sm:gap-3 max-w-[92%]">
                <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-[#00E5FF] to-blue-600 flex-shrink-0 flex items-center justify-center mt-1">
                  <Bot size={14} className="text-white" />
                </div>
                <div className="bg-[#111] border border-white/5 text-gray-300 px-4 sm:px-5 py-3 sm:py-4 rounded-2xl rounded-tl-sm text-xs sm:text-sm space-y-3">
                  {chatMode === "fast" ? (
                    <>
                      <p>The auth middleware (<code className="text-[#00E5FF] bg-[#00E5FF]/10 px-1 rounded">auth_middleware.py</code>) extracts the JWT from the <code className="text-gray-400">Authorization</code> header and decodes it.</p>
                      <p>It then calls <code className="text-[#00E5FF] bg-[#00E5FF]/10 px-1 rounded">SessionStore.get(user_id)</code> to verify the session is still active in Redis.</p>
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 text-xs text-purple-400 mb-3 bg-purple-500/10 px-3 py-2 rounded-lg border border-purple-500/20">
                        <Sparkles size={14} /> Analyzed 14 files across 3 directories
                      </div>
                      <p>The auth flow involves three main components:</p>
                      <ol className="list-decimal pl-5 space-y-2 text-gray-400">
                        <li><strong className="text-white">Middleware</strong> (<code className="text-[#00E5FF]">auth_middleware.py:42</code>): Extracts the Bearer token and verifies the signature using the public key.</li>
                        <li><strong className="text-white">Session Store</strong> (<code className="text-[#00E5FF]">redis_store.py:118</code>): A Redis-backed store that maintains active session IDs. The middleware queries this to ensure the token hasn't been revoked.</li>
                        <li><strong className="text-white">User Context</strong>: If valid, it attaches a <code className="text-white">User</code> object to the <code className="text-white">request.state</code> for downstream handlers.</li>
                      </ol>
                      <div className="bg-[#050505] p-3 rounded border border-white/5 font-mono text-xs mt-3">
                        {'session_data = await redis.get(f"session:{token_id}")'}<br/>
                        {'if not session_data:'}<br/>
                        {'    raise UnauthorizedException()'}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* User Message 2 */}
            <div className="flex justify-end">
              <div className="bg-[#222] text-white px-4 py-3 rounded-2xl rounded-tr-sm max-w-[85%] text-xs sm:text-sm">
                What happens if the session expires mid-request?
              </div>
            </div>

            {/* AI Message 2 */}
            <div className="flex justify-start">
              <div className="flex gap-2 sm:gap-3 max-w-[92%]">
                <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-[#00E5FF] to-blue-600 flex-shrink-0 flex items-center justify-center mt-1">
                  <Bot size={14} className="text-white" />
                </div>
                <div className="bg-[#111] border border-white/5 text-gray-300 px-4 sm:px-5 py-3 sm:py-4 rounded-2xl rounded-tl-sm text-xs sm:text-sm space-y-3">
                  {chatMode === "fast" ? (
                    <p>If the Redis key expires during the request execution, the current request will still complete successfully because the session check only happens in the middleware before the route handler runs.</p>
                  ) : (
                    <>
                      <p>Because the session validation occurs strictly in the <code className="text-[#00E5FF]">AuthMiddleware</code> before yielding to the route handler, a mid-request expiration in Redis does <strong>not</strong> interrupt the current request.</p>
                      <p>However, if the route handler makes secondary internal API calls that propagate the token, those downstream services will fail with a 401 if they perform their own fresh session validation.</p>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Chat Input */}
          <div className="p-3 sm:p-4 border-t border-white/5 bg-[#050505]">
            <div className="relative">
              <input 
                type="text" 
                placeholder="Ask about your code..." 
                className="w-full bg-[#111] border border-white/10 rounded-xl py-3 pl-4 pr-12 text-sm focus:outline-none focus:border-[#00E5FF]/50 text-white placeholder-gray-500"
                disabled
              />
              <button className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors">
                <ArrowRight size={18} />
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Changelog Teaser Section */}
      <section className="py-16 sm:py-24 px-4 sm:px-6 relative z-10 bg-[#050505]">
        <div className="max-w-5xl mx-auto">
          <div className="flex flex-col sm:flex-row items-start sm:items-end justify-between mb-8 sm:mb-12 gap-4">
            <div>
              <h2 className="text-2xl sm:text-3xl font-bold mb-2">Ship at velocity.</h2>
              <p className="text-gray-400">DeepDoc is constantly improving.</p>
            </div>
            <a href="/__mockup/preview/deepdoc-landing/ChangelogPage" className="text-[#00E5FF] hover:text-white transition-colors text-sm font-medium flex items-center gap-1 flex-shrink-0">
              View full changelog <ArrowRight size={14} />
            </a>
          </div>

          <div className="space-y-4 relative before:absolute before:inset-0 before:ml-5 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-gradient-to-b before:from-transparent before:via-white/10 before:to-transparent">
            
            <div className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group">
              <div className="flex items-center justify-center w-10 h-10 rounded-full border border-white/10 bg-[#0A0A0A] shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10 transition-colors group-hover:border-[#00E5FF]/50">
                <div className="w-2 h-2 rounded-full bg-[#00E5FF]"></div>
              </div>
              <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] glass-panel p-5 sm:p-6 rounded-xl border border-white/5 group-hover:border-white/10 transition-all">
                <div className="flex items-center gap-3 mb-2">
                  <span className="px-2 py-1 rounded bg-[#00E5FF]/10 text-[#00E5FF] text-xs font-mono font-bold">v1.7.0</span>
                  <span className="text-xs text-gray-500">May 2026</span>
                </div>
                <p className="text-sm text-gray-300">Token streaming for fast and deep-research chat modes. Modular v2 pipeline.</p>
              </div>
            </div>

            <div className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group">
              <div className="flex items-center justify-center w-10 h-10 rounded-full border border-white/10 bg-[#0A0A0A] shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10 transition-colors group-hover:border-purple-500/50">
                <div className="w-2 h-2 rounded-full bg-gray-600 group-hover:bg-purple-400 transition-colors"></div>
              </div>
              <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] glass-panel p-5 sm:p-6 rounded-xl border border-white/5 group-hover:border-white/10 transition-all">
                <div className="flex items-center gap-3 mb-2">
                  <span className="px-2 py-1 rounded bg-white/5 text-gray-300 text-xs font-mono font-bold">v1.6.0</span>
                  <span className="text-xs text-gray-500">Apr 2026</span>
                </div>
                <p className="text-sm text-gray-300">VS Code extension 0.0.2. Stronger grounded retrieval.</p>
              </div>
            </div>

            <div className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group">
              <div className="flex items-center justify-center w-10 h-10 rounded-full border border-white/10 bg-[#0A0A0A] shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10 transition-colors group-hover:border-blue-500/50">
                <div className="w-2 h-2 rounded-full bg-gray-600 group-hover:bg-blue-400 transition-colors"></div>
              </div>
              <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] glass-panel p-5 sm:p-6 rounded-xl border border-white/5 group-hover:border-white/10 transition-all">
                <div className="flex items-center gap-3 mb-2">
                  <span className="px-2 py-1 rounded bg-white/5 text-gray-300 text-xs font-mono font-bold">v1.5.0</span>
                  <span className="text-xs text-gray-500">Mar 2026</span>
                </div>
                <p className="text-sm text-gray-300">Chatbot mode with streaming. Multi-file context support.</p>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* CTA Footer */}
      <footer className="py-10 sm:py-12 px-4 sm:px-6 border-t border-white/5 bg-[#050505] relative z-10">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-5 sm:gap-6">
          <div className="flex items-center gap-2">
            <span className="font-mono font-bold text-xl tracking-tight text-white">DeepDoc</span>
          </div>
          
          <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-3 text-sm font-medium text-gray-500">
            <a href="https://github.com/pranav322/deepdoc" target="_blank" rel="noreferrer" className="hover:text-white transition-colors">GitHub</a>
            <a href="https://pypi.org/project/deepdoc" target="_blank" rel="noreferrer" className="hover:text-white transition-colors">PyPI</a>
            <a href="/__mockup/preview/deepdoc-landing/DocsPage" className="hover:text-white transition-colors">Docs</a>
            <a href="/__mockup/preview/deepdoc-landing/ChangelogPage" className="hover:text-white transition-colors">Changelog</a>
            <a href="https://github.com/pranav322/deepdoc/blob/main/LICENSE" target="_blank" rel="noreferrer" className="hover:text-white transition-colors">License: MIT</a>
          </div>

          <div className="flex items-center">
            <button 
              onClick={copyInstall}
              className="group flex items-center gap-2 px-4 py-2 rounded-md bg-[#111] border border-white/10 hover:border-[#00E5FF]/50 transition-all duration-300"
            >
              <Terminal size={14} className="text-gray-500 flex-shrink-0" />
              <code className="font-mono text-sm text-gray-300 group-hover:text-white transition-colors">pip install deepdoc</code>
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}
