import React, { useState, useEffect } from "react";
import { Navbar } from "./_Navbar";

type Category = "Added" | "Changed" | "Fixed" | "Maintenance";

interface ReleaseEntry {
  version: string;
  date: string;
  summary: string;
  isLatest?: boolean;
  isPatch?: boolean;
  githubUrl: string;
  sections: { category: Category; items: string[] }[];
}

const RELEASES: ReleaseEntry[] = [
  {
    version: "v1.7.0",
    date: "May 2, 2026",
    summary: "Token-by-token streaming for Fast and Deep Research chat modes.",
    isLatest: true,
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.7.0",
    sections: [
      {
        category: "Added",
        items: [
          "POST /query/stream SSE endpoint that streams Fast mode answers token-by-token before emitting a final result event.",
          "POST /deep-research/stream SSE endpoint that streams Deep Research synthesis token-by-token before emitting a final result event.",
          "complete_stream() method to LiteLLMChatClient using litellm.completion(stream=True), yielding token strings as they arrive.",
          "token_callback parameter to _complete_with_continuation(), query(), deep_research(), and _run_research_mode() so final answer generation can push tokens to any caller.",
          "synthesis_token_callback to DeepResearcher so only the synthesis step streams (sub-question expansions remain non-streaming).",
        ],
      },
      {
        category: "Changed",
        items: [
          "Updated chatbot UI so Fast and Deep modes fetch from the new /stream endpoints and progressively render answers with ReactMarkdown as tokens arrive, falling back to non-streaming endpoints if unavailable.",
        ],
      },
    ],
  },
  {
    version: "v1.6.0",
    date: "May 1, 2026",
    summary: "Evidence-grounded chatbot answers backed by a symbol corpus and SQLite FTS lexical retrieval.",
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.6.0",
    sections: [
      {
        category: "Added",
        items: [
          "Dedicated symbol corpus plus SQLite FTS lexical retrieval — chatbot search now blends exact identifier matches with semantic search.",
          "Source catalog and index manifest artifacts for deterministic evidence hydration and index inspection.",
          "Canonical chatbot evidence[], references[], and diagnostics payloads, plus /query-context alignment with the same evidence contract.",
        ],
      },
      {
        category: "Changed",
        items: [
          "Chatbot answer assembly now hydrates proof from the source archive/catalog, excludes generated/internal paths from source evidence, and treats docs as references instead of implementation proof.",
          "Generated chatbot UI surfaces evidence IDs, reference links, diagnostics, and inline evidence navigation in the answer workspace.",
          "Updated README and AGENTS guidance to match the evidence-first retrieval model, symbol indexing, lexical search, and validation behavior.",
        ],
      },
      {
        category: "Fixed",
        items: [
          "Answer-grounding gaps by validating cited evidence IDs and source paths, retrying invalid answers, and failing closed with conservative diagnostics when validation still fails.",
          "MDX hazard escaping for additional raw brace and less-than sequences emitted by generated docs.",
        ],
      },
    ],
  },
  {
    version: "v1.5.2",
    date: "April 27, 2026",
    summary: "Trust hardening: provenance frontmatter, coverage reporting, and stricter hallucination validation.",
    isPatch: true,
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.5.2",
    sections: [
      {
        category: "Added",
        items: [
          "Trust hardening for generated docs: provenance frontmatter, generated-site commit badges, coverage reporting, local setup verification, and warning-only cross-page consistency artifacts.",
        ],
      },
      {
        category: "Changed",
        items: [
          "Tightened generated-page validation for hallucinated paths, hallucinated symbols, and low file coverage on core pages.",
          "Improved chatbot trust behavior with explicit no-fabrication prompting, score-based out-of-scope abstention, stricter citation filtering, and similarity-based confidence.",
        ],
      },
    ],
  },
  {
    version: "v1.5.1",
    date: "April 25, 2026",
    summary: "Fumadocs scaffold cleanup — chatbot routes are omitted when chatbot.enabled is false.",
    isPatch: true,
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.5.1",
    sections: [
      {
        category: "Changed",
        items: [
          "Generated Fumadocs scaffold now omits chatbot routes, frontend components, and chatbot_backend/ artifacts when chatbot.enabled is false, keeping docs-only builds clean.",
        ],
      },
    ],
  },
  {
    version: "v1.5.0",
    date: "April 25, 2026",
    summary: "Scanned runtime endpoint planning enriches grouped pages instead of generating one page per route.",
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.5.0",
    sections: [
      {
        category: "Changed",
        items: [
          "Scanned runtime endpoint planning now enriches grouped endpoint-family pages instead of generating one MDX page per route, while preserving OpenAPI-backed per-route API pages when a spec exists.",
        ],
      },
      {
        category: "Fixed",
        items: [
          "Deterministic planner assignment fallback so malformed LLM JSON in the assign step no longer discards the proposed bucket plan.",
        ],
      },
    ],
  },
  {
    version: "v1.4.0",
    date: "April 17, 2026",
    summary: "Dedicated code-aware chatbot mode with live SSE trace events.",
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.4.0",
    sections: [
      {
        category: "Added",
        items: [
          "Dedicated code-aware chatbot mode with POST /code-deep and live SSE tracing via POST /code-deep/stream.",
          "Code-aware retrieval defaults, file inventory output, and generated site UI support for a third chatbot mode with live progress visibility.",
        ],
      },
      {
        category: "Changed",
        items: [
          "Updated planner nav shaping to produce a reader-first, repo-agnostic flow (Start Here → Core Workflows → API Reference → Data Model → runtime/integrations/ops) while preserving coverage.",
          "Updated endpoint-reference nav grouping to live under API Reference and dedupe legacy setup overlap.",
          "Updated database grouping to coalesce large sets of sparse singleton model groups into stable aggregate groups so coverage stays complete without one-file nav spam.",
        ],
      },
    ],
  },
  {
    version: "v1.3.0",
    date: "April 7, 2026",
    summary: "Deep-research coverage improvements, agent-style research loop, and benchmark scorecard workflows.",
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.3.0",
    sections: [
      {
        category: "Added",
        items: [
          "Source-archive persistence for chatbot indexing (source_archive.json.gz) so deep-research workflows can inspect repository files from indexed state.",
          "Agent-style deep-research loop with bounded read_file and grep tool actions over archived sources for multi-step investigation.",
          "Benchmark scorecard workflows in deepdoc benchmark, including catalog-based and artifact-proxy scoring, scorecard JSON output, and strict quality-gate enforcement.",
          "Retrieval diagnostics and API enhancements including POST /query-context and response_mode in query responses.",
          "Generated chatbot_backend/ scaffolding (app.py, schemas, settings, requirements, env example) for standalone chatbot deployment.",
        ],
      },
      {
        category: "Changed",
        items: [
          "Deep-research retrieval now combines sub-question evidence with original-question retrieval context and deeper per-step evidence budgets.",
          "Rebalanced retrieval/rerank behavior across code, artifact, docs, and relationship corpora with per-kind candidate balancing.",
          "Updated chatbot retrieval defaults and prompt-budget behavior to improve runtime, flow, and architecture question coverage.",
        ],
      },
      {
        category: "Fixed",
        items: [
          "Deep-research answer continuity by routing long step and synthesis responses through continuation-aware completion handling.",
          "Evidence-loss scenarios during reranking by preserving relationship chunks as first-class candidates in final retrieval ordering.",
        ],
      },
      {
        category: "Maintenance",
        items: [
          "Removed checked-in generated DeepDoc state and static site export artifacts (.deepdoc/*, legacy plan/file-map snapshots, and site/out/*) to keep release commits focused on source changes.",
        ],
      },
    ],
  },
  {
    version: "v1.2.0",
    date: "April 6, 2026",
    summary: "v2 modular architecture, hybrid chatbot retrieval, and generation quality reporting.",
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.2.0",
    sections: [
      {
        category: "Added",
        items: [
          "Package-based v2 architecture modules for planner, scanner, generator, and site builder to replace large monolithic files.",
          "Dedicated repo-doc chatbot corpus with configurable indexing guardrails so selected repo-authored docs are indexed separately from generated docs.",
          "Hybrid chatbot retrieval: lexical exact-match paths, graph-aware relationship expansion, adjacent code-window stitching, and richer citation payloads.",
          "/deep-research live repo fallback with bounded evidence collection while keeping normal /query index-only.",
          "Runtime extraction coverage for Django commands/signals/channels, Laravel jobs/events/listeners/scheduler, JS/TS worker and queue patterns, and Go workers.",
          "Persisted generation quality reporting at .deepdoc/generation_quality.json.",
        ],
      },
      {
        category: "Changed",
        items: [
          "Updated planner specializations and evidence assembly so runtime, config, and integration details propagate consistently into generated pages.",
          "Extended generated-page validation to enforce route/runtime/config/integration grounding when corresponding evidence exists.",
        ],
      },
      {
        category: "Fixed",
        items: [
          "Incremental chatbot sync handling for deleted generated-doc files so stale chunks are removed correctly.",
        ],
      },
    ],
  },
  {
    version: "v1.1.0",
    date: "April 4, 2026",
    summary: "Helper-function evidence, relationship corpus, and deeper chatbot retrieval.",
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.1.0",
    sections: [
      {
        category: "Added",
        items: [
          "Helper-function evidence assembly for imported repo-local utilities so feature and endpoint pages describe called helpers from actual source instead of guesses.",
          "Secondary internal-doc context and extracted environment/config evidence for overview and system-style pages.",
          "Chatbot relationship corpus with import-graph and symbol-index chunks, plus chain retrieval that pulls related code from imported files.",
          "Validation checks for unmatched route claims and references to files outside the assembled evidence set.",
        ],
      },
      {
        category: "Changed",
        items: [
          "Evidence extraction thresholds now follow config and expanded large-file excerpts so generated pages keep more real branch logic, symbol bodies, and owned code paths.",
          "Tightened generation prompts to require grounded business logic, helper behavior, config knobs, constants, file coverage tables, and clearer uncertainty handling.",
          "Reworked Fumadocs OpenAPI support to build API pages from the staged manifest and surface OpenAPI operations in navigation when endpoint pages are absent.",
          "Increased default chatbot retrieval and answer budgets so responses can include more code, artifacts, docs, and relationship context in a single answer.",
          "Hardened Mermaid cleanup by sanitizing problematic flowchart edge labels.",
        ],
      },
    ],
  },
  {
    version: "v1.0.0",
    date: "April 3, 2026",
    summary: "First stable release. Major improvements to planning, retrieval, and release automation.",
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v1.0.0",
    sections: [
      {
        category: "Added",
        items: [
          "Source classification and publication-tier metadata across scanning, planning, persistence, generation, and chatbot indexing.",
          "Publishability filtering for runtime API endpoints so generated API structure only includes validated product routes.",
          "First-party versus third-party integration classification so internal systems are documented as subsystems instead of external integrations.",
          "FAISS index loading support in chatbot retrieval paths and new retrieval metadata such as framework, source kind, publication tier, and trust score.",
          "Concurrency controls for generation with --max-parallel-workers and --rate-limit-pause.",
          "Site dependency sync stamping so serve and deploy can detect stale node_modules more reliably.",
        ],
      },
      {
        category: "Changed",
        items: [
          "Reworked planner behavior to prefer fewer, deeper pages instead of over-splitting concepts into many shallow buckets.",
          "Raised decomposition thresholds, parallelized giant-file clustering, and added post-planning bucket consolidation for near-duplicate pages.",
          "Improved landing-page generation with a repository-wide map, richer overview prompts, stronger framework awareness, and better routing into deeper docs pages.",
          "Updated chatbot retrieval ranking to prefer core runtime/docs evidence by default while still allowing tests, fixtures, examples, and generated artifacts to surface when explicitly requested.",
          "Hardened MDX and Mermaid normalization, including safer Step heading handling, indented code-fence normalization, and ER diagram cleanup.",
          "Split GitHub release creation into changelog-driven notes when a matching version section exists, with auto-generated notes as the fallback.",
        ],
      },
    ],
  },
  {
    version: "v0.1.1",
    date: "April 1, 2026",
    summary: "First public PyPI release.",
    githubUrl: "https://github.com/tss-pranavkumar/deepdoc/releases/tag/v0.1.1",
    sections: [
      {
        category: "Added",
        items: [
          "Published DeepDoc to PyPI.",
          "Improved package metadata for the PyPI project page.",
          "Installation instructions for pip install deepdoc.",
          "Documented deepdoc[chatbot] for chatbot features.",
          "Automated release workflow scaffolding for future releases.",
        ],
      },
    ],
  },
];

const CATEGORY_COLOR: Record<Category, string> = {
  Added:       "#0891b2",
  Changed:     "#6b7280",
  Fixed:       "#6b7280",
  Maintenance: "#6b7280",
};

export function ChangelogPage() {
  const [activeVersion, setActiveVersion] = useState("v1.7.0");

  useEffect(() => {
    const handleScroll = () => {
      const entries = document.querySelectorAll<HTMLElement>("[data-version]");
      let current = "v1.7.0";
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

        {/* Left Sidebar — matches DocsPage exactly */}
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
            Showing all {RELEASES.length} releases from v0.1.1 to v1.7.0.{" "}
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
