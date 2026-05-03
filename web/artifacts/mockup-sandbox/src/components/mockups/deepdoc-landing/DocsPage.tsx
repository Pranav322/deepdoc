import React, { useState, useEffect } from "react";
import { Copy, CheckCircle2 } from "lucide-react";
import { Navbar } from "./_Navbar";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      onClick={copy}
      title="Copy"
      style={{
        position: "absolute", top: 10, right: 10,
        background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 6, padding: "4px 8px", cursor: "pointer", display: "flex",
        alignItems: "center", gap: 4, fontSize: 11, color: copied ? "#4ade80" : "#9ca3af",
        transition: "all 0.15s"
      }}
      onMouseEnter={e => { if (!copied) (e.currentTarget as HTMLButtonElement).style.color = "#e5e7eb"; }}
      onMouseLeave={e => { if (!copied) (e.currentTarget as HTMLButtonElement).style.color = "#9ca3af"; }}
    >
      {copied ? <CheckCircle2 size={13} /> : <Copy size={13} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function CodeBlock({ children, code }: { children: React.ReactNode; code: string }) {
  return (
    <div style={{ position: "relative", marginBottom: "1.5rem" }}>
      <pre style={{
        background: "#1e1e1e", color: "#d4d4d4", padding: "1.25rem 1.25rem 1.25rem 1.25rem",
        borderRadius: 8, overflowX: "auto", fontFamily: "'JetBrains Mono', monospace",
        fontSize: "0.875rem", lineHeight: 1.6, margin: 0, paddingRight: 80
      }}>
        <code>{children}</code>
      </pre>
      <CopyButton text={code} />
    </div>
  );
}

const TOC_ITEMS = [
  { id: "introduction", label: "Introduction" },
  { id: "installation", label: "Installation" },
  { id: "quick-start", label: "Quick Start" },
  { id: "deepdoc-generate", label: "deepdoc generate" },
  { id: "deepdoc-chat", label: "deepdoc chat" },
  { id: "configuration", label: "Configuration" },
  { id: "vscode-extension", label: "VS Code Extension" },
  { id: "chatbot-modes", label: "Chatbot Modes" },
  { id: "changelog", label: "Changelog" },
];

const ID_TO_LABEL: Record<string, string> = Object.fromEntries(TOC_ITEMS.map(t => [t.id, t.label]));

export function DocsPage() {
  const [activeSection, setActiveSection] = useState("quick-start");

  const [expandedNav, setExpandedNav] = useState<Record<string, boolean>>({
    "Getting Started": true,
    "CLI Reference": true,
    "Configuration": true,
    "VS Code Extension": false,
    "Chatbot Modes": false,
    "Changelog": false,
  });

  const toggleNav = (section: string) =>
    setExpandedNav(prev => ({ ...prev, [section]: !prev[section] }));

  useEffect(() => {
    const handleScroll = () => {
      const sections = document.querySelectorAll<HTMLElement>("h2[id], h3[id]");
      let current = "";
      sections.forEach(el => {
        if (window.scrollY >= el.offsetTop - 120) current = el.id;
      });
      if (current && ID_TO_LABEL[current]) setActiveSection(current);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const sidebarLink = (href: string, label: string) => {
    const id = href.replace("#", "");
    const isActive = activeSection === id;
    return (
      <a
        key={href}
        href={href}
        style={{
          display: "block", fontSize: 13, padding: "5px 16px",
          marginLeft: -1, borderLeft: `2px solid ${isActive ? "#0891b2" : "transparent"}`,
          color: isActive ? "#0891b2" : "#4b5563",
          fontWeight: isActive ? 600 : 400,
          background: isActive ? "#ecfeff" : "transparent",
          textDecoration: "none", borderRadius: "0 4px 4px 0",
          transition: "all 0.15s"
        }}
        onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLAnchorElement).style.color = "#111827"; }}
        onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLAnchorElement).style.color = "#4b5563"; }}
        onClick={e => {
          e.preventDefault();
          document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
          setActiveSection(id);
        }}
      >
        {label}
      </a>
    );
  };

  return (
    <div style={{ minHeight: "100vh", background: "#fff", color: "#111827", fontFamily: "'Inter', sans-serif", display: "flex", flexDirection: "column" }}>
      <style dangerouslySetInnerHTML={{ __html: `
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        .docs-h2 { font-size: 1.5rem; font-weight: 700; margin-top: 3rem; margin-bottom: 1rem; padding-bottom: 0.75rem; border-bottom: 1px solid #e5e7eb; color: #111827; }
        .docs-h3 { font-size: 1.125rem; font-weight: 600; margin-top: 2rem; margin-bottom: 0.75rem; color: #1f2937; }
        .docs-p { margin-bottom: 1.25rem; line-height: 1.75; color: #374151; font-size: 0.9375rem; }
        .docs-ul { list-style-type: disc; padding-left: 1.5rem; margin-bottom: 1.5rem; color: #374151; font-size: 0.9375rem; }
        .docs-ol { list-style-type: decimal; padding-left: 1.5rem; margin-bottom: 1.5rem; color: #374151; font-size: 0.9375rem; }
        .docs-li { margin-bottom: 0.5rem; line-height: 1.7; }
        .docs-code { font-family: 'JetBrains Mono', monospace; font-size: 0.8125em; background: #f3f4f6; padding: 0.15em 0.45em; border-radius: 4px; color: #111827; border: 1px solid #e5e7eb; }
        .docs-table { width: 100%; border-collapse: collapse; margin-bottom: 2rem; font-size: 0.875rem; }
        .docs-table th { border-bottom: 2px solid #e5e7eb; padding: 0.625rem 1rem; font-weight: 600; color: #111827; text-align: left; background: #f9fafb; }
        .docs-table td { border-bottom: 1px solid #f3f4f6; padding: 0.625rem 1rem; color: #4b5563; }
        .docs-table tr:hover td { background: #f9fafb; }
        .callout-green { background: #ecfdf5; border-left: 4px solid #10b981; padding: 0.875rem 1rem; border-radius: 0 8px 8px 0; margin-bottom: 1.5rem; }
        .callout-blue { background: #eff6ff; border-left: 4px solid #3b82f6; padding: 0.875rem 1rem; border-radius: 0 8px 8px 0; margin-bottom: 1.5rem; }
        .callout-yellow { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 0.875rem 1rem; border-radius: 0 8px 8px 0; margin-bottom: 1.5rem; }
        .kbd { display: inline-block; font-family: 'JetBrains Mono', monospace; font-size: 0.8em; padding: 2px 7px; background: #f3f4f6; border: 1px solid #d1d5db; border-bottom-width: 2px; border-radius: 5px; color: #374151; }
      ` }} />

      <Navbar />

      <div style={{ flex: 1, maxWidth: 1400, width: "100%", margin: "0 auto", display: "flex", alignItems: "flex-start" }}>

        {/* Left Sidebar */}
        <aside style={{
          width: 260, flexShrink: 0, position: "sticky", top: 64,
          height: "calc(100vh - 64px)", overflowY: "auto",
          borderRight: "1px solid #e5e7eb", background: "#f9fafb",
          padding: "28px 12px"
        }}>
          {([
            {
              group: "Getting Started",
              links: [
                { href: "#introduction", label: "Introduction" },
                { href: "#installation", label: "Installation" },
                { href: "#quick-start", label: "Quick Start" },
              ]
            },
            {
              group: "CLI Reference",
              links: [
                { href: "#deepdoc-generate", label: "deepdoc generate" },
                { href: "#deepdoc-chat", label: "deepdoc chat" },
              ]
            },
            {
              group: "Configuration",
              links: [
                { href: "#configuration", label: "deepdoc.yaml" },
              ]
            },
            {
              group: "VS Code Extension",
              links: [
                { href: "#vscode-extension", label: "Installing the Extension" },
              ]
            },
            {
              group: "Chatbot Modes",
              links: [
                { href: "#chatbot-modes", label: "Fast Mode & Deep Research" },
              ]
            },
            {
              group: "Changelog",
              links: [
                { href: "#changelog", label: "All Releases" },
              ]
            },
          ] as { group: string; links: { href: string; label: string }[] }[]).map(({ group, links }) => (
            <div key={group} style={{ marginBottom: 20 }}>
              <button
                onClick={() => toggleNav(group)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  width: "100%", background: "none", border: "none", padding: "4px 8px",
                  fontSize: 12, fontWeight: 600, color: "#111827", letterSpacing: "0.04em",
                  textTransform: "uppercase", cursor: "pointer", marginBottom: 4
                }}
              >
                {group}
                <span style={{ fontSize: 16, color: "#9ca3af", lineHeight: 1 }}>{expandedNav[group] ? "−" : "+"}</span>
              </button>
              {expandedNav[group] && (
                <div style={{ borderLeft: "2px solid #e5e7eb", marginLeft: 8, paddingTop: 2, paddingBottom: 2 }}>
                  {links.map(l => sidebarLink(l.href, l.label))}
                </div>
              )}
            </div>
          ))}
        </aside>

        {/* Main Content */}
        <main style={{ flex: 1, minWidth: 0, padding: "40px 48px 80px", maxWidth: 800 }}>

          <div style={{ fontSize: 12, fontWeight: 600, color: "#0891b2", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>GETTING STARTED</div>
          <h1 style={{ fontSize: "2.25rem", fontWeight: 700, color: "#111827", marginBottom: 16, lineHeight: 1.2 }}>Quick Start Guide</h1>
          <p style={{ fontSize: "1.125rem", color: "#6b7280", marginBottom: 40, lineHeight: 1.7 }}>
            Install DeepDoc and generate your first documentation in under 2 minutes.
          </p>

          {/* INTRODUCTION */}
          <h2 id="introduction" className="docs-h2">Introduction</h2>
          <p className="docs-p">
            DeepDoc is an AI-powered documentation engine for Python engineers. It reads your codebase, maps the architecture, and outputs structured markdown documentation — automatically kept in sync as your code evolves. Unlike static documentation tools, DeepDoc re-generates documentation on every run so your docs are always accurate.
          </p>
          <p className="docs-p">
            DeepDoc supports two modes: a <strong>CLI generator</strong> that writes markdown files to disk, and an interactive <strong>chat mode</strong> that lets you ask natural-language questions about your codebase in real time.
          </p>

          {/* INSTALLATION */}
          <h2 id="installation" className="docs-h2">Installation</h2>
          <p className="docs-p">Install the CLI globally or within your project's virtual environment using pip:</p>
          <CodeBlock code={"pip install deepdoc\n# Verify install\ndeepcdoc --version".replace(/deepcdoc/g, "deepdoc")}>
            <span style={{ color: "#ce9178" }}>pip</span> install deepdoc{"\n"}
            <span style={{ color: "#6a9955" }}># Verify install</span>{"\n"}
            <span style={{ color: "#ce9178" }}>deepdoc</span> --version
          </CodeBlock>
          <div className="callout-green">
            <strong style={{ color: "#065f46", display: "block", marginBottom: 4 }}>Requirements</strong>
            <span style={{ color: "#047857" }}>DeepDoc requires Python 3.10 or higher and an <code className="docs-code">OPENAI_API_KEY</code> environment variable set to a valid OpenAI key.</span>
          </div>

          {/* QUICK START */}
          <h2 id="quick-start" className="docs-h2">Quick Start</h2>
          <p className="docs-p">Follow these steps to generate documentation for an existing project:</p>
          <ol className="docs-ol">
            <li className="docs-li">Navigate to your project root in the terminal</li>
            <li className="docs-li">Run <code className="docs-code">deepdoc generate</code> — by default it reads <code className="docs-code">./</code> and writes to <code className="docs-code">./docs/</code></li>
            <li className="docs-li">Open <code className="docs-code">./docs/deepdoc-output.md</code> to read your generated documentation</li>
            <li className="docs-li">Run <code className="docs-code">deepdoc chat</code> to start asking questions about your code</li>
          </ol>
          <CodeBlock code={"cd /path/to/your/project\ndeepcdoc generate --path ./src --output ./docs\n# Documentation generated at ./docs/deepdoc-output.md".replace(/deepcdoc/g, "deepdoc")}>
            <span style={{ color: "#569cd6" }}>cd</span> /path/to/your/project{"\n"}
            <span style={{ color: "#ce9178" }}>deepdoc</span> generate --path <span style={{ color: "#dcdcaa" }}>./src</span> --output <span style={{ color: "#dcdcaa" }}>./docs</span>{"\n"}
            <span style={{ color: "#6a9955" }}># Documentation generated at ./docs/deepdoc-output.md</span>
          </CodeBlock>
          <p className="docs-p">To keep your docs automatically in sync as you develop, use the <code className="docs-code">--watch</code> flag. DeepDoc will re-generate the affected sections whenever a Python file changes:</p>
          <CodeBlock code={"deepdoc generate --path ./src --watch"}>
            <span style={{ color: "#ce9178" }}>deepdoc</span> generate --path <span style={{ color: "#dcdcaa" }}>./src</span> --watch
          </CodeBlock>

          {/* CLI REFERENCE — generate */}
          <h2 id="deepdoc-generate" className="docs-h2">CLI Reference — deepdoc generate</h2>
          <p className="docs-p">The <code className="docs-code">generate</code> command is the core engine of DeepDoc. It traverses your directory, builds a syntax tree, embeds code chunks, and passes structured context to the LLM to produce markdown.</p>
          <table className="docs-table">
            <thead>
              <tr>
                <th>Flag</th>
                <th>Default</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["--path", "./", "Path to the Python project root to analyze"],
                ["--output", "./docs", "Output directory where markdown files will be saved"],
                ["--model", "gpt-4o", "LLM model to use (requires OPENAI_API_KEY)"],
                ["--depth", "full", "Analysis depth: shallow (fast) or full (comprehensive)"],
                ["--format", "markdown", "Output format: markdown or json"],
                ["--watch", "—", "Re-run generation whenever source files change"],
                ["--ignore", "—", "Glob pattern of paths to exclude (can repeat)"],
              ].map(([flag, def, desc]) => (
                <tr key={flag}>
                  <td><code className="docs-code">{flag}</code></td>
                  <td><code className="docs-code">{def}</code></td>
                  <td>{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3 className="docs-h3">Example — Full run with custom output</h3>
          <CodeBlock code={"deepdoc generate \\\n  --path ./src \\\n  --output ./docs \\\n  --depth full \\\n  --format markdown"}>
            <span style={{ color: "#ce9178" }}>deepdoc</span> generate \{"\n"}
            {"  "}--path <span style={{ color: "#dcdcaa" }}>./src</span> \{"\n"}
            {"  "}--output <span style={{ color: "#dcdcaa" }}>./docs</span> \{"\n"}
            {"  "}--depth <span style={{ color: "#dcdcaa" }}>full</span> \{"\n"}
            {"  "}--format <span style={{ color: "#dcdcaa" }}>markdown</span>
          </CodeBlock>

          {/* CLI REFERENCE — chat */}
          <h2 id="deepdoc-chat" className="docs-h2">CLI Reference — deepdoc chat</h2>
          <p className="docs-p">The interactive chat mode lets you ask natural-language questions about your codebase directly from the terminal. DeepDoc uses your locally-generated embeddings to answer questions grounded in your actual code.</p>
          <CodeBlock code={"# Fast mode — sub-second answers using lightweight retrieval\ndeepcdoc chat --path ./src --mode fast\n\n# Deep research mode — multi-hop reasoning, slower but thorough\ndeepcdoc chat --path ./src --mode deep-research".replace(/deepcdoc/g, "deepdoc")}>
            <span style={{ color: "#6a9955" }}># Fast mode — sub-second answers using lightweight retrieval</span>{"\n"}
            <span style={{ color: "#ce9178" }}>deepdoc</span> chat --path <span style={{ color: "#dcdcaa" }}>./src</span> --mode <span style={{ color: "#dcdcaa" }}>fast</span>{"\n"}{"\n"}
            <span style={{ color: "#6a9955" }}># Deep research mode — multi-hop reasoning, slower but thorough</span>{"\n"}
            <span style={{ color: "#ce9178" }}>deepdoc</span> chat --path <span style={{ color: "#dcdcaa" }}>./src</span> --mode <span style={{ color: "#dcdcaa" }}>deep-research</span>
          </CodeBlock>
          <div className="callout-blue">
            <strong style={{ color: "#1e40af", display: "block", marginBottom: 4 }}>Deep Research Latency</strong>
            <span style={{ color: "#1d4ed8" }}>Deep research mode performs multi-hop retrieval and iterative re-ranking. Expect 3–8 seconds per query. Ideal for complex architectural questions that require reasoning across multiple files.</span>
          </div>

          {/* CONFIGURATION */}
          <h2 id="configuration" className="docs-h2">Configuration</h2>
          <p className="docs-p">DeepDoc reads a <code className="docs-code">deepdoc.yaml</code> file from your project root if one exists, eliminating the need to pass flags on every invocation. CLI flags always override config file values.</p>
          <CodeBlock code={"# deepdoc.yaml\npath: ./src\noutput: ./docs\nmodel: gpt-4o\ndepth: full\nformat: markdown\nignore:\n  - \"**/__pycache__/**\"\n  - \"**/tests/**\"\n  - \"**/migrations/**\""}>
            <span style={{ color: "#6a9955" }}># deepdoc.yaml</span>{"\n"}
            <span style={{ color: "#9cdcfe" }}>path</span>: <span style={{ color: "#ce9178" }}>./src</span>{"\n"}
            <span style={{ color: "#9cdcfe" }}>output</span>: <span style={{ color: "#ce9178" }}>./docs</span>{"\n"}
            <span style={{ color: "#9cdcfe" }}>model</span>: <span style={{ color: "#ce9178" }}>gpt-4o</span>{"\n"}
            <span style={{ color: "#9cdcfe" }}>depth</span>: <span style={{ color: "#ce9178" }}>full</span>{"\n"}
            <span style={{ color: "#9cdcfe" }}>format</span>: <span style={{ color: "#ce9178" }}>markdown</span>{"\n"}
            <span style={{ color: "#9cdcfe" }}>ignore</span>:{"\n"}
            {"  "}- <span style={{ color: "#ce9178" }}>"**/__pycache__/**"</span>{"\n"}
            {"  "}- <span style={{ color: "#ce9178" }}>"**/tests/**"</span>{"\n"}
            {"  "}- <span style={{ color: "#ce9178" }}>"**/migrations/**"</span>
          </CodeBlock>
          <h3 className="docs-h3">Environment Variables</h3>
          <p className="docs-p">DeepDoc reads the following environment variables at startup:</p>
          <table className="docs-table">
            <thead>
              <tr><th>Variable</th><th>Required</th><th>Description</th></tr>
            </thead>
            <tbody>
              {[
                ["OPENAI_API_KEY", "Yes", "Your OpenAI API key. Required for all generation and chat operations."],
                ["DEEPDOC_MODEL", "No", "Default model override. Equivalent to --model flag."],
                ["DEEPDOC_LOG_LEVEL", "No", "Logging verbosity: DEBUG, INFO, WARNING. Defaults to INFO."],
              ].map(([v, req, desc]) => (
                <tr key={v}>
                  <td><code className="docs-code">{v}</code></td>
                  <td style={{ color: req === "Yes" ? "#dc2626" : "#6b7280" }}>{req}</td>
                  <td>{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* VS CODE EXTENSION */}
          <h2 id="vscode-extension" className="docs-h2">VS Code Extension</h2>
          <p className="docs-p">
            The DeepDoc VS Code extension brings documentation directly into your editor. Hover over any function, class, or module that DeepDoc has analyzed and see AI-generated documentation inline — without leaving your file.
          </p>
          <h3 className="docs-h3">Installing the Extension</h3>
          <p className="docs-p">Search for <strong>DeepDoc</strong> in the VS Code Extensions Marketplace, or install it from the CLI:</p>
          <CodeBlock code={"code --install-extension deepdoc.deepdoc-vscode"}>
            <span style={{ color: "#ce9178" }}>code</span> --install-extension <span style={{ color: "#dcdcaa" }}>deepdoc.deepdoc-vscode</span>
          </CodeBlock>
          <div className="callout-yellow">
            <strong style={{ color: "#92400e", display: "block", marginBottom: 4 }}>Pre-requisite</strong>
            <span style={{ color: "#78350f" }}>You must run <code className="docs-code">deepdoc generate</code> at least once before the extension can surface documentation. The extension reads the generated output from your <code className="docs-code">./docs/</code> directory.</span>
          </div>
          <h3 className="docs-h3">Keyboard Shortcuts</h3>
          <table className="docs-table">
            <thead>
              <tr><th>Action</th><th>macOS</th><th>Windows / Linux</th></tr>
            </thead>
            <tbody>
              {[
                ["Show DeepDoc panel", "⌘ Shift D", "Ctrl Shift D"],
                ["Generate docs for current file", "⌘ Shift G", "Ctrl Shift G"],
                ["Toggle inline tooltips", "⌘ Shift T", "Ctrl Shift T"],
                ["Open chat for selection", "⌘ Shift C", "Ctrl Shift C"],
              ].map(([action, mac, win]) => (
                <tr key={action}>
                  <td>{action}</td>
                  <td><kbd className="kbd">{mac}</kbd></td>
                  <td><kbd className="kbd">{win}</kbd></td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* CHATBOT MODES */}
          <h2 id="chatbot-modes" className="docs-h2">Chatbot Modes</h2>
          <p className="docs-p">
            DeepDoc's chat interface supports two distinct retrieval strategies. You choose based on the complexity of your question and the latency you can tolerate.
          </p>
          <h3 className="docs-h3">Fast Mode</h3>
          <p className="docs-p">
            Fast mode uses pre-computed dense embeddings stored locally after your last <code className="docs-code">deepdoc generate</code> run. It performs a single vector similarity lookup to retrieve the most relevant code chunks, then passes them to the LLM.
          </p>
          <ul className="docs-ul">
            <li className="docs-li">Average latency: <strong>~800ms</strong></li>
            <li className="docs-li">Best for: point lookups — "Where is the payment handler?", "What does <code className="docs-code">normalize_input()</code> do?"</li>
            <li className="docs-li">Accuracy: high for direct questions, lower for cross-cutting architectural questions</li>
          </ul>
          <CodeBlock code={"deepdoc chat --path ./src --mode fast"}>
            <span style={{ color: "#ce9178" }}>deepdoc</span> chat --path <span style={{ color: "#dcdcaa" }}>./src</span> --mode <span style={{ color: "#dcdcaa" }}>fast</span>
          </CodeBlock>
          <h3 className="docs-h3">Deep Research Mode</h3>
          <p className="docs-p">
            Deep research mode performs iterative multi-hop retrieval: it generates sub-queries, retrieves relevant chunks for each, re-ranks them, synthesizes an intermediate answer, then refines it. This makes it dramatically more accurate for complex architectural questions.
          </p>
          <ul className="docs-ul">
            <li className="docs-li">Average latency: <strong>3–8 seconds</strong> per query</li>
            <li className="docs-li">Best for: architectural questions — "How does caching interact with the ORM under high concurrency?", "Trace the data flow from the HTTP handler to the database write."</li>
            <li className="docs-li">Accuracy: significantly higher for multi-file, cross-layer questions</li>
          </ul>
          <CodeBlock code={"deepdoc chat --path ./src --mode deep-research"}>
            <span style={{ color: "#ce9178" }}>deepdoc</span> chat --path <span style={{ color: "#dcdcaa" }}>./src</span> --mode <span style={{ color: "#dcdcaa" }}>deep-research</span>
          </CodeBlock>

          {/* CHANGELOG */}
          <h2 id="changelog" className="docs-h2">Changelog</h2>
          <p className="docs-p">All notable changes to DeepDoc are documented here. Follows <a href="https://semver.org" style={{ color: "#0891b2" }} target="_blank" rel="noreferrer">Semantic Versioning</a>.</p>

          <h3 className="docs-h3" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            v1.7.0 — May 2026
            <span style={{ fontSize: 11, fontWeight: 500, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0", borderRadius: 20, padding: "2px 10px" }}>Latest</span>
          </h3>
          <ul className="docs-ul">
            <li className="docs-li">Token streaming for both fast and deep-research chat modes — responses now stream word-by-word</li>
            <li className="docs-li">Modular v2 pipeline: AST parsing, embedding, and generation are now separate stages that can be resumed independently</li>
            <li className="docs-li">Added support for custom ignore patterns via <code className="docs-code">deepdoc.yaml</code></li>
            <li className="docs-li">VS Code extension: improved hover tooltip rendering for long docstrings</li>
            <li className="docs-li">Fix: generation no longer fails on projects with circular imports</li>
          </ul>

          <h3 className="docs-h3">v1.6.0 — April 2026</h3>
          <ul className="docs-ul">
            <li className="docs-li">VS Code extension 0.0.2 released on the VS Code Marketplace</li>
            <li className="docs-li">Stronger grounded retrieval: switched to dense bi-encoder embeddings, reducing hallucination rate by ~40%</li>
            <li className="docs-li">Added <code className="docs-code">--depth shallow</code> flag for fast, surface-level documentation runs</li>
            <li className="docs-li">Fix: session tracking for multi-turn chat conversations now persists correctly across re-runs</li>
          </ul>

          <h3 className="docs-h3">v1.5.0 — March 2026</h3>
          <ul className="docs-ul">
            <li className="docs-li">Introduced chatbot mode (<code className="docs-code">deepdoc chat</code>) with streaming output</li>
            <li className="docs-li">Multi-file context support: questions can now span across up to 20 source files simultaneously</li>
            <li className="docs-li">Added <code className="docs-code">--format json</code> output option for programmatic consumption of documentation</li>
            <li className="docs-li">Improved Python 3.12 compatibility</li>
          </ul>

          <div style={{ height: 80 }} />
        </main>

        {/* Right TOC */}
        <aside style={{
          width: 220, flexShrink: 0, position: "sticky", top: 64,
          height: "calc(100vh - 64px)", padding: "36px 20px 36px 0", overflowY: "auto"
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#111827", marginBottom: 12, letterSpacing: "0.08em", textTransform: "uppercase" }}>On This Page</div>
          <nav style={{ display: "flex", flexDirection: "column", gap: 2, borderLeft: "2px solid #e5e7eb", paddingLeft: 0 }}>
            {TOC_ITEMS.map(({ id, label }) => {
              const isActive = activeSection === id;
              return (
                <a
                  key={id}
                  href={`#${id}`}
                  style={{
                    fontSize: 13, padding: "4px 0 4px 14px",
                    marginLeft: -2,
                    borderLeft: `2px solid ${isActive ? "#0891b2" : "transparent"}`,
                    color: isActive ? "#0891b2" : "#6b7280",
                    fontWeight: isActive ? 600 : 400,
                    textDecoration: "none", transition: "all 0.15s"
                  }}
                  onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLAnchorElement).style.color = "#111827"; }}
                  onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLAnchorElement).style.color = "#6b7280"; }}
                  onClick={e => {
                    e.preventDefault();
                    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
                    setActiveSection(id);
                  }}
                >
                  {label}
                </a>
              );
            })}
          </nav>
        </aside>

      </div>
    </div>
  );
}
