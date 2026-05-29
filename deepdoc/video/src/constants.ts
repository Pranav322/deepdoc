// Design tokens — synced with deepdoc.dev web site
export const C = {
  bg:           "#09090D",
  surface:      "#10101A",
  surfaceRaised:"#181820",
  line:         "rgba(255,255,255,0.06)",
  lineStrong:   "rgba(255,255,255,0.11)",
  ink:          "#F0EFEA",
  inkMuted:     "#7E7D76",
  inkFaint:     "#44433C",
  accent:       "#C2FF4D",   // chartreuse — matches web
  accentDim:    "rgba(194,255,77,0.12)",
  accentGlow:   "rgba(194,255,77,0.22)",
  blue:         "#3778FF",
  purple:       "#9B7FFF",
  teal:         "#00E5A0",
  orange:       "#FF9E00",
  pink:         "#FF5F87",
};

export const F = {
  sans: '"DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
  mono: '"JetBrains Mono", "SF Mono", "Menlo", "Monaco", "Consolas", monospace',
  display: '"DM Serif Display", Georgia, "Times New Roman", serif',
};

// Scene timing @ 30 fps — total ~32 s
export const T = {
  INTRO_START:      0,
  INTRO_DURATION:   120,   // 4 s

  PROBLEM_START:    120,
  PROBLEM_DURATION: 105,   // 3.5 s

  TERMINAL_START:   225,
  TERMINAL_DURATION:210,   // 7 s

  PIPELINE_START:   435,
  PIPELINE_DURATION:210,   // 7 s  (was 16 s)

  RESULT_START:     645,
  RESULT_DURATION:  180,   // 6 s

  OUTRO_START:      825,
  OUTRO_DURATION:   135,   // 4.5 s

  TOTAL:            960,   // 32 s
};
