import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F, SPRING } from "../constants";
import { PLANNER_STEPS, PLAN_TABLE } from "../data";

// Three real planner steps. Each gets its own band sized to how much copy
// it holds (step 1 has five lines, step 2 has three) so nothing gets cut
// off mid-fade-in — a fixed equal split left the longest step's last line
// appearing while the panel was already dissolving. Bands crossfade at
// their seams, and the last one dissolves into a glimpse of the real
// bucket-plan table instead of just ending on text.
const STEP_START = 18;
const STEP_DURATIONS = [78, 60, 66] as const; // sums to 204
const STEP_BOUNDS = STEP_DURATIONS.reduce<number[]>(
  (acc, d) => [...acc, acc[acc.length - 1] + d],
  [STEP_START]
); // [18, 96, 156, 222]
const CROSSFADE = 14;
const TABLE_START = STEP_BOUNDS[3] - 22; // 200 — starts fading in just before step 3 fades out

const toneColor = (tone: "ok" | "warn" | "muted") =>
  tone === "ok" ? C.accent : tone === "warn" ? C.orange : C.inkMuted;

const toneIcon = (tone: "ok" | "warn" | "muted") =>
  tone === "ok" ? "✓" : tone === "warn" ? "⚠" : "·";

export const PlannerScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [278, 300], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const headerSpring = spring({ frame, fps, config: SPRING.soft });

  let activeStepIndex = 0;
  for (let i = 0; i < 3; i++) {
    if (frame >= STEP_BOUNDS[i]) activeStepIndex = i;
  }

  const tableProgress = interpolate(frame, [TABLE_START, TABLE_START + 26], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{
      background: C.bg, opacity,
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
      padding: "0 64px",
    }}>
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: `radial-gradient(ellipse 55% 48% at 50% 90%, rgba(255,95,135,0.10) 0%, transparent 70%)`,
      }} />

      {/* Header */}
      <div style={{ marginBottom: 32, textAlign: "center" }}>
        <div style={{
          fontFamily: F.mono, fontSize: 14, color: C.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
          marginBottom: 14, opacity: fadeIn,
        }}>
          Phase 2 / 5 · Planning
        </div>
        <h2 style={{
          fontFamily: F.sans, fontSize: 58, fontWeight: 800,
          color: C.ink, margin: 0, letterSpacing: "-0.035em",
          opacity: headerSpring,
          transform: `translateY(${(1 - headerSpring) * 26}px)`,
        }}>
          Then it figures out{" "}
          <span style={{
            background: `linear-gradient(135deg, ${C.pink}, ${C.accent})`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          }}>
            how to explain it.
          </span>
        </h2>
      </div>

      {/* Step dots */}
      <div style={{ display: "flex", gap: 12, marginBottom: 26, opacity: fadeIn }}>
        {PLANNER_STEPS.map((s, i) => (
          <div key={s.step} style={{
            display: "flex", alignItems: "center", gap: 9,
            padding: "9px 20px", borderRadius: 100,
            border: `1px solid ${i === activeStepIndex ? C.pink : C.lineStrong}`,
            background: i === activeStepIndex ? "rgba(255,95,135,0.12)" : "transparent",
            fontFamily: F.mono, fontSize: 14,
            color: i === activeStepIndex ? C.pink : C.inkFaint,
          }}>
            <span style={{
              width: 7, height: 7, borderRadius: "50%",
              background: i <= activeStepIndex ? C.pink : C.inkFaint,
            }} />
            {s.step}
          </div>
        ))}
      </div>

      {/* Panel stack: steps crossfade into each other, then into the table */}
      <div style={{ position: "relative", width: "100%", maxWidth: 1792, flex: 1, minHeight: 0 }}>
        {PLANNER_STEPS.map((step, i) => {
          const bandStart = STEP_BOUNDS[i];
          const bandEnd = STEP_BOUNDS[i + 1];
          const stepOpacity = Math.min(
            interpolate(frame, [bandStart, bandStart + CROSSFADE], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            }),
            interpolate(frame, [bandEnd - CROSSFADE, bandEnd], [1, 0], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            })
          );
          if (stepOpacity <= 0.001) return null;
          const localFrame = frame - bandStart;

          return (
            <div key={step.step} style={{
              position: "absolute", inset: 0,
              borderRadius: 22, border: `1px solid ${C.lineStrong}`,
              background: C.surface, opacity: stepOpacity,
              padding: "44px 52px", display: "flex", flexDirection: "column",
              justifyContent: "center",
            }}>
              <div style={{
                fontFamily: F.mono, fontSize: 16, color: C.pink,
                letterSpacing: "0.06em", marginBottom: 26,
              }}>
                {step.step} · {step.title}
              </div>
              {step.lines.map((line, li) => {
                const lStart = 14 + li * 8;
                const lo = interpolate(localFrame, [lStart, lStart + 10], [0, 1], {
                  extrapolateLeft: "clamp", extrapolateRight: "clamp",
                });
                const shift = interpolate(localFrame, [lStart, lStart + 10], [10, 0], {
                  extrapolateLeft: "clamp", extrapolateRight: "clamp",
                });
                return (
                  <div key={li} style={{
                    display: "flex", alignItems: "flex-start", gap: 14,
                    opacity: lo, transform: `translateY(${shift}px)`,
                    marginBottom: 20, fontFamily: F.mono, fontSize: 24,
                    color: line.tone === "muted" ? C.inkFaint : C.ink,
                  }}>
                    <span style={{ color: toneColor(line.tone), width: 22 }}>{toneIcon(line.tone)}</span>
                    <span>{line.text}</span>
                  </div>
                );
              })}
            </div>
          );
        })}

        {/* Bucket plan table — the payoff of the three planning steps */}
        {tableProgress > 0.01 && (
          <div style={{
            position: "absolute", inset: 0,
            borderRadius: 22, border: `1px solid ${C.accent}40`,
            background: C.surface, opacity: tableProgress,
            padding: "32px 40px", boxShadow: `0 0 70px ${C.accentDim}`,
            display: "flex", flexDirection: "column", justifyContent: "center",
          }}>
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              marginBottom: 20,
            }}>
              <span style={{ fontFamily: F.mono, fontSize: 16, color: C.accent, letterSpacing: "0.06em" }}>
                Documentation plan · 19 pages
              </span>
              <span style={{ fontFamily: F.mono, fontSize: 14, color: C.inkFaint }}>
                resolved in 105s
              </span>
            </div>
            {PLAN_TABLE.map((row, i) => {
              const rStart = TABLE_START + 14 + i * 7;
              const ro = interpolate(frame, [rStart, rStart + 9], [0, 1], {
                extrapolateLeft: "clamp", extrapolateRight: "clamp",
              });
              return (
                <div key={row.name} style={{
                  display: "flex", alignItems: "center", gap: 18,
                  padding: "11px 0", opacity: ro,
                  borderBottom: i < PLAN_TABLE.length - 1 ? `1px solid ${C.line}` : "none",
                  fontFamily: F.sans, fontSize: 18,
                }}>
                  <span style={{ color: C.ink, fontWeight: 600, flex: 1.5 }}>{row.name}</span>
                  <span style={{ color: C.inkMuted, flex: 1, fontFamily: F.mono, fontSize: 15 }}>{row.section}</span>
                  <span style={{ color: C.inkFaint, width: 76, fontFamily: F.mono, fontSize: 15 }}>{row.files} files</span>
                  <span style={{ color: C.inkFaint, flex: 1.4, fontFamily: F.mono, fontSize: 14, textAlign: "right" }}>
                    {row.deps === "—" ? "—" : `↳ ${row.deps}`}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
