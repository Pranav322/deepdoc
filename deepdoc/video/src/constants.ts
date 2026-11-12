// Design tokens, matching web/src/styles/tokens.css (dark theme): warm
// charcoal, cream ink and one vermilion accent with its tonal ramp.
import { FONT_MONO, FONT_SANS, FONT_SERIF } from "./fonts";

export const C = {
  bg: "#0D0D0C",
  surface: "#131312",
  surfaceRaised: "#1A1A18",
  line: "rgba(236,234,227,0.09)",
  lineStrong: "rgba(236,234,227,0.16)",
  grid: "rgba(236,234,227,0.05)",
  ink: "#ECEAE3",
  inkMuted: "#A3A199",
  inkFaint: "#6F6D65",
  accent: "#FF5A2B",
  accentDim: "rgba(255,90,43,0.14)",
  accentLine: "rgba(255,90,43,0.5)",
  ramp: ["#D9360B", "#FF5A2B", "#FF8548", "#FFB27A", "#ECEAE3"],
};

export const F = {
  sans: `${FONT_SANS}, -apple-system, "Helvetica Neue", Arial, sans-serif`,
  mono: `${FONT_MONO}, "SF Mono", Menlo, monospace`,
  serif: `${FONT_SERIF}, Georgia, serif`,
};

export const SPRING = {
  soft: { damping: 200, stiffness: 120, mass: 0.9 },
  snappy: { damping: 200, stiffness: 220, mass: 0.7 },
};

export const FPS = 30;

// One continuous piece in four parts. Each part overlaps the next by OVERLAP
// frames so the terminal rises as the hook fades, and the site opens over the
// finished run.
export const T = {
  INTRO: 180,    // 6 s hook
  TERMINAL: 570, // 19 s
  BROWSER: 480,  // 16 s
  OUTRO: 135,    // 4.5 s
  OVERLAP: 30,
};
export const TERMINAL_START = T.INTRO - T.OVERLAP;
export const BROWSER_START = TERMINAL_START + T.TERMINAL - T.OVERLAP;
export const OUTRO_START = BROWSER_START + T.BROWSER - T.OVERLAP;
export const TOTAL_DURATION = OUTRO_START + T.OUTRO;
