import React, { useState } from "react";
import { Terminal, Github, Copy, CheckCircle2 } from "lucide-react";

export function Navbar() {
  const [copied, setCopied] = useState(false);

  const copyInstall = () => {
    navigator.clipboard.writeText("pip install deepdoc");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <nav style={{ position: "sticky", top: 0, zIndex: 50, width: "100%", borderBottom: "1px solid rgba(255,255,255,0.1)", background: "rgba(5,5,5,0.85)", backdropFilter: "blur(12px)" }}>
      <div style={{ maxWidth: 1400, margin: "0 auto", padding: "0 24px", height: 64, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, fontSize: 20, letterSpacing: "-0.02em", color: "#fff" }}>DeepDoc</span>
          <span style={{ padding: "2px 8px", borderRadius: 6, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", fontSize: 11, fontFamily: "monospace", color: "#9ca3af" }}>v1.7.0</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 32, fontSize: 14, fontWeight: 500, color: "#9ca3af" }}>
          <a href="/__mockup/preview/deepdoc-landing/DocsPage" style={{ color: "inherit", textDecoration: "none" }} onMouseEnter={e => (e.currentTarget.style.color = "#fff")} onMouseLeave={e => (e.currentTarget.style.color = "#9ca3af")}>Documentation</a>
          <a href="/__mockup/preview/deepdoc-landing/ChangelogPage" style={{ color: "inherit", textDecoration: "none" }} onMouseEnter={e => (e.currentTarget.style.color = "#fff")} onMouseLeave={e => (e.currentTarget.style.color = "#9ca3af")}>Changelog</a>
          <a href="https://github.com/pranav322/deepdoc" target="_blank" rel="noreferrer" style={{ color: "inherit", textDecoration: "none", display: "flex", alignItems: "center", gap: 4 }} onMouseEnter={e => (e.currentTarget.style.color = "#fff")} onMouseLeave={e => (e.currentTarget.style.color = "#9ca3af")}>
            <Github size={14} /> GitHub
          </a>
        </div>
        <button
          onClick={copyInstall}
          style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", borderRadius: 8, background: "#111", border: "1px solid rgba(255,255,255,0.1)", cursor: "pointer", transition: "border-color 0.2s" }}
          onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(0,229,255,0.5)")}
          onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(255,255,255,0.1)")}
        >
          <Terminal size={14} color="#6b7280" />
          <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: "#d1d5db" }}>pip install deepdoc</code>
          {copied ? <CheckCircle2 size={14} color="#00E5FF" /> : <Copy size={14} color="#6b7280" />}
        </button>
      </div>
    </nav>
  );
}
