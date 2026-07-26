// Design tokens — synced with deepdoc.dev web site
import { FONT_DISPLAY, FONT_MONO, FONT_SANS } from "./fonts";

export const C = {
  bg:           "#09090D",
  surface:      "#10101A",
  surfaceRaised:"#181820",
  line:         "rgba(255,255,255,0.06)",
  lineStrong:   "rgba(255,255,255,0.11)",
  ink:          "#F0EFEA",
  inkMuted:     "#9A9992",
  inkFaint:     "#55544C",
  accent:       "#C2FF4D",   // chartreuse — matches web, the only "brand" hue
  accentDim:    "rgba(194,255,77,0.12)",
  accentGlow:   "rgba(194,255,77,0.22)",
  // No blue or purple anywhere in the palette by request — every secondary
  // hue below sits next to chartreuse on a warm/cool axis that still reads
  // as one cohesive dark-SaaS palette instead of a rainbow of accents.
  teal:         "#00E5A0",
  orange:       "#FF9E00",
  pink:         "#FF5F87",
};

// Loaded via @remotion/google-fonts (see fonts.ts) so these are real webfont
// families guaranteed present before the first frame renders — previously
// these were plain CSS strings with nothing registering the font, so every
// scene silently rendered in fallback Arial/Helvetica Bold.
export const F = {
  sans: `${FONT_SANS}, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif`,
  mono: `${FONT_MONO}, "SF Mono", "Menlo", "Monaco", "Consolas", monospace`,
  display: `${FONT_DISPLAY}, Georgia, "Times New Roman", serif`,
};

// Shared spring configs so every scene settles with the same weight of
// motion instead of each one improvising its own damping/stiffness.
export const SPRING = {
  soft:   { damping: 200, stiffness: 130, mass: 0.9 },
  snappy: { damping: 200, stiffness: 210, mass: 0.7 },
  drift:  { damping: 200, stiffness: 80,  mass: 1.1 },
};

// Scene timing @ 30 fps. Scenes are stitched with a crossfade
// (see DeepDocVideo.tsx's TransitionSeries), so each transition eats
// TRANSITION_DURATION frames from the total — hard cuts read as a
// slideshow, a short crossfade reads as one continuous piece.
export const T = {
  INTRO_DURATION:      105,  // 3.5 s
  PROBLEM_DURATION:    105,  // 3.5 s
  SCAN_DURATION:       165,  // 5.5 s
  PLANNER_DURATION:    300,  // 10 s
  GENERATE_DURATION:   195,  // 6.5 s
  BUILD_DURATION:      135,  // 4.5 s
  RESULT_DURATION:     180,  // 6 s
  OUTRO_DURATION:      135,  // 4.5 s

  TRANSITION_DURATION: 15,   // 0.5 s crossfade between each scene
};

const SCENE_DURATIONS = [
  T.INTRO_DURATION,
  T.PROBLEM_DURATION,
  T.SCAN_DURATION,
  T.PLANNER_DURATION,
  T.GENERATE_DURATION,
  T.BUILD_DURATION,
  T.RESULT_DURATION,
  T.OUTRO_DURATION,
];

// Start frame of each scene in the final composed (post-crossfade) timeline —
// used to place cross-scene cues at the right absolute frame.
export const SCENE_STARTS = SCENE_DURATIONS.reduce<number[]>((acc, duration, i) => {
  if (i === 0) return [0];
  const prevStart = acc[i - 1];
  const prevDuration = SCENE_DURATIONS[i - 1];
  acc.push(prevStart + prevDuration - T.TRANSITION_DURATION);
  return acc;
}, []);

export const TOTAL_DURATION =
  SCENE_DURATIONS.reduce((sum, d) => sum + d, 0) -
  T.TRANSITION_DURATION * (SCENE_DURATIONS.length - 1);
