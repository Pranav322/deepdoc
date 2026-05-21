// Design tokens matching deepdoc.dev web site
export const C = {
  bg: "#0a0a0a",
  surface: "#111111",
  surfaceRaised: "#161616",
  line: "rgba(255,255,255,0.06)",
  lineStrong: "rgba(255,255,255,0.12)",
  ink: "#ededed",
  inkMuted: "#8b8b8b",
  inkFaint: "#525252",
  accent: "#00E5FF",
  accentDim: "rgba(0,229,255,0.16)",
};

export const F = {
  sans: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Helvetica, Arial, sans-serif',
  mono: '"SF Mono", "Menlo", "Monaco", "Consolas", monospace',
};

// Scene timing in frames @ 30 fps — total 43 s
export const T = {
  INTRO_START: 0,
  INTRO_DURATION: 120,    // 4 s
  PROBLEM_START: 120,
  PROBLEM_DURATION: 120,  // 4 s
  TERMINAL_START: 240,
  TERMINAL_DURATION: 240, // 8 s
  PIPELINE_START: 480,
  PIPELINE_DURATION: 480, // 16 s
  RESULT_START: 960,
  RESULT_DURATION: 180,   // 6 s
  OUTRO_START: 1140,
  OUTRO_DURATION: 150,    // 5 s
  TOTAL: 1290,
};
