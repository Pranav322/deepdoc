import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { Caption, type Cue } from "../components/Caption";
import { Window } from "../components/Window";
import { C, F, T } from "../constants";
import { BUILD_STATS, BUILD_TIMINGS, GENERATION_LOG, GENERATION_QUEUED, GENERATION_TOTAL_PAGES, PLANNER_STEPS, SCAN_LOG } from "../data";

// The terminal is a recreation, but every line of output is the real text of
// a real run (see data.ts). Only the pacing is ours: the run took 6m 12s.

type Tone = "ink" | "muted" | "faint" | "accent" | "warn";
type Seg = { t: string; tone?: Tone; bold?: boolean };
type Line = { at: number; segs: Seg[]; bar?: boolean };

const COLOUR: Record<Tone, string> = { ink: C.ink, muted: C.inkMuted, faint: C.inkFaint, accent: C.accent, warn: C.ramp[3] };
const COMMAND = "deepdoc generate";
const TYPE_FROM = 20, TYPE_STEP = 2;
const ENTER = TYPE_FROM + COMMAND.length * TYPE_STEP + 6;

const lines: Line[] = [];
let f = ENTER + 8;
const push = (segs: Seg[], gap = 6, extra: Partial<Line> = {}) => { lines.push({ at: f, segs, ...extra }); f += gap; };
const header = (t: string) => push([{ t, tone: "ink", bold: true }], 10);
const blank = () => push([{ t: " " }], 3);

// Phase 1: scan (verbatim).
const SCAN_AT = f;
for (const raw of SCAN_LOG) {
  if (raw === "") blank();
  else if (raw.startsWith("Phase")) header(raw);
  else if (raw.startsWith("✓")) push([{ t: "✓ ", tone: "accent" }, { t: raw.slice(2), tone: "muted" }], 8);
  else if (raw.startsWith("  ")) {
    const m = raw.match(/^(\s+.*?\.+\s)(.*)$/);
    push(m ? [{ t: m[1], tone: "faint" }, { t: m[2], tone: "ink" }] : [{ t: raw, tone: "muted" }], 5);
  } else push([{ t: raw, tone: "muted" }], 8);
}

// Phase 2: plan (verbatim steps and lines).
f += 8; blank();
const PLAN_AT = f;
header("Phase 2/5 · Planning");
for (const step of PLANNER_STEPS) {
  push([{ t: `  ${step.step} `, tone: "accent" }, { t: step.title, tone: "ink" }], 8);
  for (const l of step.lines) {
    if (l.tone === "ok") push([{ t: "  ✓ ", tone: "accent" }, { t: l.text, tone: "muted" }], 7);
    else if (l.tone === "warn") push([{ t: "  ! ", tone: "warn" }, { t: l.text, tone: "warn" }], 7);
    else push([{ t: `    ${l.text}`, tone: "faint" }], 7);
  }
}

// Phase 3: generate (verbatim page rows).
f += 8; blank();
const GEN_AT = f;
header(`Phase 3/5 · Generating ${GENERATION_TOTAL_PAGES} pages`);
const BAR_FROM = f;
for (const g of GENERATION_LOG) {
  push([{ t: "  ✓ ", tone: "accent" }, { t: g.title.padEnd(30), tone: "ink" }, { t: g.meta.padEnd(46), tone: "faint" }, { t: g.time, tone: "muted" }], 20);
}
push([{ t: "  … ", tone: "faint" }, { t: GENERATION_QUEUED, tone: "muted" }], 14);
push([], 62, { bar: true });
const BAR_TO = f - 8;

// Phase 5: build (verbatim summary).
blank();
const BUILD_AT = f;
header("Phase 5/5 · Building site");
push([{ t: `  ${BUILD_TIMINGS}`, tone: "faint" }], 10);
for (let i = 0; i < BUILD_STATS.length; i += 2) {
  const [a, b] = [BUILD_STATS[i], BUILD_STATS[i + 1]];
  const cell = (s: { label: string; value: string }): Seg[] => [
    { t: `  ${s.label} `.padEnd(20, "."), tone: "faint" },
    { t: ` ${s.value}`.padEnd(12), tone: s.value === "success" ? "accent" : "ink" },
  ];
  push([...cell(a), ...cell(b)], 6);
}

export const TERMINAL_END_OF_OUTPUT = f;

const W = 1500, H = 800, LH = 35, PAD_Y = 30;
const VISIBLE = Math.floor((H - 50 - PAD_Y * 2) / LH);

const cues: Cue[] = [
  { from: 6, to: SCAN_AT - 2, title: "A real run on a real repository", note: "Pranav322/youtube-notes" },
  { from: SCAN_AT, to: PLAN_AT - 4, index: "1/5", title: "Scan", note: "local · no LLM" },
  { from: PLAN_AT, to: GEN_AT - 4, index: "2/5", title: "Plan", note: "a few LLM calls" },
  { from: GEN_AT, to: BUILD_AT - 4, index: "3/5", title: "Generate", note: "one call per page" },
  { from: BUILD_AT, to: T.TERMINAL - T.OVERLAP, index: "5/5", title: "Build", note: "19 pages · 0 invalid" },
];

export const Terminal = () => {
  const frame = useCurrentFrame();

  // The body scrolls up one line each time a line arrives below the fold.
  let scroll = 0;
  lines.forEach((l, i) => {
    if (i + 2 >= VISIBLE) scroll += LH * interpolate(frame, [l.at, l.at + 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  });

  const typed = COMMAND.slice(0, Math.max(0, Math.floor((frame - TYPE_FROM) / TYPE_STEP)));
  const typing = frame < ENTER;
  const caretOn = Math.floor(frame / 15) % 2 === 0;

  const pushIn = interpolate(frame, [0, T.TERMINAL], [1, 1.04]);
  const exit = interpolate(frame, [T.TERMINAL - T.OVERLAP, T.TERMINAL], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
  const enter = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  const barP = interpolate(frame, [BAR_FROM, BAR_TO], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.quad) });
  const done = Math.round(barP * GENERATION_TOTAL_PAGES);

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: enter * (1 - exit * 0.75), transform: `translateY(${(1 - enter) * 30 - exit * 40 - 14}px) scale(${pushIn * (1 - exit * 0.08)})`, filter: `blur(${exit * 6}px)` }}>
        <Window title="youtube-notes — zsh" width={W} height={H}>
          <div style={{ position: "absolute", left: 40, right: 40, top: PAD_Y, transform: `translateY(${-scroll}px)`, fontFamily: F.mono, fontSize: 21, lineHeight: `${LH}px`, whiteSpace: "pre", color: C.ink }}>
            <div>
              <span style={{ color: C.inkFaint }}>~/youtube-notes </span>
              <span style={{ color: C.accent }}>$ </span>
              {typed}
              {typing && <span style={{ display: "inline-block", width: 12, height: 24, verticalAlign: "text-bottom", background: caretOn ? C.accent : "transparent" }} />}
            </div>
            <div> </div>
            {lines.map((l, i) => {
              if (frame < l.at) return null;
              const o = interpolate(frame, [l.at, l.at + 5], [0, 1], { extrapolateRight: "clamp" });
              if (l.bar) {
                return (
                  <div key={i} style={{ opacity: o, display: "flex", alignItems: "center", gap: 18, height: LH, paddingLeft: 26 }}>
                    <div style={{ width: 620, height: 8, borderRadius: 4, background: C.line, overflow: "hidden" }}>
                      <div style={{ width: `${barP * 100}%`, height: "100%", background: C.accent }} />
                    </div>
                    <span style={{ color: C.ink }}>{done}/{GENERATION_TOTAL_PAGES}</span>
                    <span style={{ color: C.inkFaint }}>pages</span>
                  </div>
                );
              }
              return (
                <div key={i} style={{ opacity: o, transform: `translateY(${(1 - o) * 6}px)`, height: LH }}>
                  {l.segs.map((s, n) => <span key={n} style={{ color: COLOUR[s.tone ?? "ink"], fontWeight: s.bold ? 700 : 400 }}>{s.t}</span>)}
                </div>
              );
            })}
          </div>
        </Window>
      </AbsoluteFill>

      <div style={{ position: "absolute", right: 96, top: 46, fontFamily: F.mono, fontSize: 17, color: C.inkFaint, opacity: enter * (1 - exit) }}>
        real output · 6m 12s run, sped up
      </div>
      <div style={{ opacity: 1 - exit }}><Caption cues={cues} /></div>
    </AbsoluteFill>
  );
};
