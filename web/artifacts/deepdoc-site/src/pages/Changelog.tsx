import React, { useState, useEffect } from "react";
import { Navbar } from "../components/Navbar";
import RELEASES from "virtual:changelog-data";

type Category = "Added" | "Changed" | "Fixed" | "Maintenance";

const CATEGORY_COLOR: Record<Category, string> = {
  Added:       "#0891b2",
  Changed:     "#6b7280",
  Fixed:       "#6b7280",
  Maintenance: "#6b7280",
};

export function ChangelogPage() {
  const latestVersion = RELEASES[0]?.version ?? "";
  const [activeVersion, setActiveVersion] = useState(latestVersion);

  useEffect(() => {
    const handleScroll = () => {
      const entries = document.querySelectorAll<HTMLElement>("[data-version]");
      let current = latestVersion;
      entries.forEach(el => {
        if (window.scrollY >= el.offsetTop - 120) current = el.getAttribute("data-version") || current;
      });
      setActiveVersion(current);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div style={{ minHeight: "100vh", background: "#fff", color: "#111827", fontFamily: "'Inter', sans-serif" }}>
      <style dangerouslySetInnerHTML={{ __html: `
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: #f9fafb; }
        ::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }
        .cl-nav-link { transition: color 0.12s; }
        .cl-nav-link:hover { color: #111827 !important; }
        .cl-gh-link { transition: all 0.12s; }
        .cl-gh-link:hover { background: #f3f4f6 !important; color: #111827 !important; }
      `}} />

      <Navbar />

      {/* Page Header */}
      <div style={{ borderBottom: "1px solid #e5e7eb", padding: "48px 48px 40px", background: "#fff" }}>
        <div style={{ maxWidth: 1400, margin: "0 auto" }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#0891b2", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>
            Release History
          </div>
          <h1 style={{ fontSize: "2rem", fontWeight: 700, margin: "0 0 10px", color: "#111827", letterSpacing: "-0.02em" }}>
            Changelog
          </h1>
          <p style={{ color: "#6b7280", fontSize: "0.9375rem", margin: 0, lineHeight: 1.6 }}>
            All notable changes to DeepDoc, sourced from the{" "}
            <a href="https://github.com/tss-pranavkumar/deepdoc/blob/main/CHANGELOG.md" target="_blank" rel="noreferrer"
              style={{ color: "#0891b2", textDecoration: "none" }}>
              GitHub repository
            </a>
            . Follows Semantic Versioning.
          </p>
        </div>
      </div>

      <div style={{ maxWidth: 1400, margin: "0 auto", display: "flex" }}>

        {/* Left Sidebar */}
        <aside style={{
          width: 220, flexShrink: 0, position: "sticky", top: 64,
          height: "calc(100vh - 64px)", overflowY: "auto",
          borderRight: "1px solid #e5e7eb", background: "#f9fafb",
          padding: "28px 12px"
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#111827", letterSpacing: "0.04em", textTransform: "uppercase", padding: "4px 8px", marginBottom: 6 }}>
            Versions
          </div>
          <nav>
            {RELEASES.map(r => {
              const isActive = activeVersion === r.version;
              return (
                <a
                  key={r.version}
                  className="cl-nav-link"
                  href={`#${r.version}`}
                  onClick={e => {
                    e.preventDefault();
                    document.getElementById(r.version)?.scrollIntoView({ behavior: "smooth" });
                    setActiveVersion(r.version);
                  }}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    fontSize: 13, padding: "5px 16px",
                    marginLeft: -1,
                    borderLeft: `2px solid ${isActive ? "#0891b2" : "transparent"}`,
                    color: isActive ? "#0891b2" : "#4b5563",
                    fontWeight: isActive ? 600 : 400,
                    background: isActive ? "#ecfeff" : "transparent",
                    textDecoration: "none", borderRadius: "0 4px 4px 0",
                    transition: "all 0.15s"
                  }}
                >
                  <span style={{ fontFamily: "monospace" }}>{r.version}</span>
                  {r.isLatest && (
                    <span style={{ fontSize: 10, fontWeight: 600, color: "#0891b2", background: "#ecfeff", border: "1px solid #a5f3fc", borderRadius: 10, padding: "1px 6px" }}>
                      new
                    </span>
                  )}
                </a>
              );
            })}
          </nav>
        </aside>

        {/* Main Content */}
        <main style={{ flex: 1, minWidth: 0, padding: "40px 64px 80px 64px", maxWidth: 860 }}>
          {RELEASES.map((release, idx) => (
            <div
              key={release.version}
              id={release.version}
              data-version={release.version}
              style={{
                paddingBottom: 56,
                marginBottom: 56,
                borderBottom: idx < RELEASES.length - 1 ? "1px solid #e5e7eb" : "none"
              }}
            >
              {/* Release Header */}
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 16, gap: 16, flexWrap: "wrap" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
                    <h2 style={{ margin: 0, fontSize: "1.375rem", fontWeight: 700, color: "#111827", fontFamily: "monospace", letterSpacing: "-0.01em" }}>
                      {release.version}
                    </h2>
                    {release.isLatest && (
                      <span style={{ fontSize: 11, fontWeight: 600, color: "#0891b2", border: "1px solid #a5f3fc", background: "#ecfeff", borderRadius: 20, padding: "2px 10px" }}>
                        Latest
                      </span>
                    )}
                    {release.isPatch && (
                      <span style={{ fontSize: 11, fontWeight: 500, color: "#9ca3af", border: "1px solid #e5e7eb", background: "#f9fafb", borderRadius: 20, padding: "2px 10px" }}>
                        Patch
                      </span>
                    )}
                    <span style={{ fontSize: 13, color: "#9ca3af" }}>{release.date}</span>
                  </div>
                  <p style={{ margin: 0, color: "#6b7280", fontSize: "0.9375rem", lineHeight: 1.65 }}>
                    {release.summary}
                  </p>
                </div>
                <a
                  href={release.githubUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="cl-gh-link"
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    padding: "5px 12px", borderRadius: 6, flexShrink: 0,
                    border: "1px solid #e5e7eb", background: "#fff",
                    color: "#6b7280", textDecoration: "none",
                    fontSize: 12, fontWeight: 500, whiteSpace: "nowrap"
                  }}
                >
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
                  </svg>
                  View Release
                </a>
              </div>

              {/* Category Sections */}
              <div style={{ display: "flex", flexDirection: "column", gap: 24, marginTop: 24 }}>
                {release.sections.map(section => (
                  <div key={section.category}>
                    <div style={{
                      fontSize: 12, fontWeight: 600, color: CATEGORY_COLOR[section.category],
                      textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10
                    }}>
                      {section.category}
                    </div>
                    <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                      {section.items.map((item, i) => (
                        <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10, color: "#374151", fontSize: "0.9rem", lineHeight: 1.7 }}>
                          <span style={{ flexShrink: 0, marginTop: 8, width: 4, height: 4, borderRadius: "50%", background: "#d1d5db" }} />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* Footer note */}
          <p style={{ fontSize: "0.875rem", color: "#9ca3af", textAlign: "center" }}>
            Showing all {RELEASES.length} releases from {RELEASES[RELEASES.length - 1]?.version} to {RELEASES[0]?.version}.{" "}
            <a href="https://github.com/tss-pranavkumar/deepdoc/releases" target="_blank" rel="noreferrer" style={{ color: "#0891b2", textDecoration: "none" }}>
              View all on GitHub
            </a>
            .
          </p>
        </main>

      </div>
    </div>
  );
}
