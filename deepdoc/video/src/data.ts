// Real output from an actual `deepdoc generate` run (youtube-notes repo).
// Every number and string below is copied verbatim from a real terminal
// session — nothing in Scan/Planner/Generate scenes is invented copy.

export const SCAN_METRICS = [
  { label: "Source files", value: "56" },
  { label: "API endpoints", value: "7" },
  { label: "Frameworks", value: "FastAPI" },
  { label: "Config files", value: "8" },
] as const;

export const SCAN_LANG_SPLIT = [
  { label: "python", value: 16 },
  { label: "typescript", value: 9 },
  { label: "javascript", value: 2 },
] as const;

export const SCAN_LOG = [
  "Generating docs for youtube-notes",
  "",
  "Phase 1/5 · Scanning repository",
  "  Source files ......... 56",
  "  API endpoints ......... 7",
  "  Frameworks ....... fastapi",
  "  Entry points .......... 1",
  "  Config files .......... 8",
  "",
  "✓ 2 endpoint bundle(s) built",
  "✓ Found 8 integration signals across 6 files",
] as const;

export type PlannerStep = {
  step: string;
  title: string;
  lines: Array<{ text: string; tone: "ok" | "warn" | "muted" }>;
};

export const PLANNER_STEPS: PlannerStep[] = [
  {
    step: "Step 1/3",
    title: "Naming topology clusters",
    lines: [
      { text: "Named 15 topology clusters across 5 sections", tone: "ok" },
      { text: "API Layer · Data Layer · Frontend UI · Note Processing · Infra", tone: "muted" },
      { text: "Repo profile: backend_service (confidence: high)", tone: "ok" },
      { text: "Found 3 cross-cutting concerns: database, rate limiting, errors", tone: "ok" },
      { text: "1 giant file detected — flagged for special handling", tone: "warn" },
    ],
  },
  {
    step: "Step 2/3",
    title: "Proposing documentation buckets",
    lines: [
      { text: "Proposed 18 buckets from the named clusters", tone: "ok" },
      { text: "5 architecture · 5 feature · 1 database · 1 endpoint family", tone: "muted" },
      { text: "1 glossary · 1 introduction · 1 setup · 1 testing", tone: "muted" },
    ],
  },
  {
    step: "Step 3/3",
    title: "Assigning files, resolving dependencies",
    lines: [
      { text: "Decomposed broad buckets, consolidated near-duplicates", tone: "ok" },
      { text: "Grouped 7 endpoints into one family page", tone: "ok" },
      { text: "Validated 100% file coverage — nothing left orphaned", tone: "ok" },
      { text: "Full plan resolved in 105s", tone: "muted" },
    ],
  },
];

export const PLAN_TABLE = [
  { name: "Introduction", section: "—", files: 0, deps: "—" },
  { name: "Getting Started", section: "Start Here", files: 0, deps: "introduction" },
  { name: "Database Schema & Migrations", section: "Data Model", files: 4, deps: "getting-started" },
  { name: "Notes API", section: "Note Processing", files: 7, deps: "database, ai-service" },
  { name: "Transcript Service", section: "Note Processing", files: 1, deps: "notes-api" },
  { name: "Job Management", section: "Note Processing", files: 2, deps: "database, notes-api" },
  { name: "API Proxy Route", section: "API Layer", files: 1, deps: "getting-started" },
  { name: "Debugging & Observability", section: "Supporting Infra", files: 1, deps: "getting-started" },
] as const;

export const GENERATION_LOG: Array<{
  title: string;
  meta: string;
  time: string;
  warnings?: number;
}> = [
  { title: "Notes API", meta: "endpoint family · 7 files · ~3,455 words", time: "43.1s", warnings: 2 },
  { title: "Database Schema & Migrations", meta: "database · 4 files · ~2,293 words", time: "52.7s", warnings: 1 },
  { title: "Getting Started", meta: "setup · ~2,067 words", time: "63.2s", warnings: 1 },
];

export const GENERATION_QUEUED = "Development Notes";
export const GENERATION_TOTAL_PAGES = 19;

// Real "Phase 5/5: Building site" completion summary — the actual box the
// CLI prints once a run finishes.
export const BUILD_TIMINGS = "scan=0.08s · plan=105.14s · generate=266.68s · build=0.03s";

export const BUILD_STATS = [
  { label: "Files scanned", value: "56" },
  { label: "Pages planned", value: "19" },
  { label: "Pages generated", value: "19" },
  { label: "Status", value: "success" },
  { label: "Invalid pages", value: "0" },
  { label: "Degraded pages", value: "0" },
  { label: "Warnings", value: "40" },
  { label: "API reference", value: "no" },
] as const;
