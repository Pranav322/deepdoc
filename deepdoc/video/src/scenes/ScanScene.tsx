import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F, SPRING } from "../constants";
import { SCAN_LANG_SPLIT, SCAN_METRICS } from "../data";

// Real numbers from an actual `deepdoc generate` run — nothing here is a
// stand-in stat, which is what makes a dev-tool demo feel credible instead
// of generic.
const STAT_START = 30;
const STAT_STEP = 10;

const Counter = ({ target, frame, start }: { target: string; frame: number; start: number }) => {
  const numeric = parseInt(target, 10);
  if (Number.isNaN(numeric)) {
    // Non-numeric value (e.g. "FastAPI") — just fade/settle, no count-up.
    const p = interpolate(frame, [start, start + 18], [0, 1], {
      extrapolateLeft: "clamp", extrapolateRight: "clamp",
    });
    return <>{target}<span style={{ opacity: 1 - p }} /></>;
  }
  const p = interpolate(frame, [start, start + 24], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const shown = Math.round(numeric * p);
  return <>{shown}</>;
};

// Full-bleed layout — the first cut boxed everything into a narrow 1440px
// column with a lot of dead black margin either side and a ~340px-tall
// panel; this version uses almost the full 1920 canvas and much larger
// type so the real numbers are actually legible at a glance.
export const ScanScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [140, 165], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const headerSpring = spring({ frame, fps, config: SPRING.soft });
  const panelSpring  = spring({ frame: Math.max(0, frame - 10), fps, config: SPRING.soft });

  return (
    <AbsoluteFill style={{
      background: C.bg, opacity,
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
      padding: "0 64px",
    }}>
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: `radial-gradient(ellipse 55% 45% at 50% 10%, rgba(0,229,160,0.12) 0%, transparent 70%)`,
      }} />

      {/* Header */}
      <div style={{ marginBottom: 46, textAlign: "center" }}>
        <div style={{
          fontFamily: F.mono, fontSize: 14, color: C.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
          marginBottom: 16, opacity: fadeIn,
        }}>
          Phase 1 / 5 · Scanning
        </div>
        <h2 style={{
          fontFamily: F.sans, fontSize: 60, fontWeight: 800,
          color: C.ink, margin: 0, letterSpacing: "-0.035em",
          opacity: headerSpring,
          transform: `translateY(${(1 - headerSpring) * 26}px)`,
        }}>
          It reads your repo{" "}
          <span style={{
            background: `linear-gradient(135deg, ${C.teal}, ${C.accent})`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          }}>
            before writing a word.
          </span>
        </h2>
      </div>

      <div style={{
        display: "flex", gap: 26, width: "100%", maxWidth: 1792, flex: 1,
        opacity: panelSpring, transform: `translateY(${(1 - panelSpring) * 30}px)`,
      }}>
        {/* Stat cards */}
        <div style={{ flex: 1.1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          {SCAN_METRICS.map((m, i) => {
            const start = STAT_START + i * STAT_STEP;
            const cardSpring = spring({ frame: Math.max(0, frame - start), fps, config: SPRING.snappy });
            return (
              <div key={m.label} style={{
                border: `1px solid ${C.lineStrong}`,
                borderRadius: 20, background: C.surface,
                padding: "34px 30px 28px",
                display: "flex", flexDirection: "column", justifyContent: "center",
                opacity: cardSpring,
                transform: `translateY(${(1 - cardSpring) * 18}px)`,
              }}>
                <div style={{
                  fontFamily: F.sans, fontSize: 68, fontWeight: 800,
                  color: C.ink, letterSpacing: "-0.02em", marginBottom: 10, lineHeight: 1,
                }}>
                  <Counter target={m.value} frame={frame} start={start} />
                </div>
                <div style={{
                  fontFamily: F.mono, fontSize: 16, color: C.inkFaint,
                  letterSpacing: "0.03em",
                }}>
                  {m.label}
                </div>
              </div>
            );
          })}
        </div>

        {/* Real terminal panel */}
        <div style={{
          flex: 1, borderRadius: 20, border: `1px solid ${C.lineStrong}`,
          background: C.surface, overflow: "hidden",
          display: "flex", flexDirection: "column",
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            borderBottom: `1px solid ${C.line}`, padding: "15px 22px",
            background: C.surfaceRaised,
          }}>
            <div style={{ display: "flex", gap: 7 }}>
              <span style={{ width: 11, height: 11, borderRadius: "50%", background: "rgba(255,95,86,0.65)" }} />
              <span style={{ width: 11, height: 11, borderRadius: "50%", background: "rgba(255,189,46,0.65)" }} />
              <span style={{ width: 11, height: 11, borderRadius: "50%", background: "rgba(39,201,63,0.65)" }} />
            </div>
            <span style={{ margin: "0 auto", fontFamily: F.mono, fontSize: 13, color: C.inkFaint }}>
              deepdoc generate
            </span>
          </div>
          <div style={{ padding: "32px 34px", fontFamily: F.mono, fontSize: 19, lineHeight: 2.1, flex: 1 }}>
            {SCAN_LANG_SPLIT.map((row, i) => {
              const start = 46 + i * 10;
              const lo = interpolate(frame, [start, start + 12], [0, 1], {
                extrapolateLeft: "clamp", extrapolateRight: "clamp",
              });
              const barW = interpolate(frame, [start, start + 22], [0, row.value], {
                extrapolateLeft: "clamp", extrapolateRight: "clamp",
              });
              return (
                <div key={row.label} style={{ opacity: lo, display: "flex", alignItems: "center", gap: 16, marginBottom: 10 }}>
                  <span style={{ color: C.inkMuted, width: 130 }}>{row.label}</span>
                  <div style={{ flex: 1, height: 9, borderRadius: 4, background: C.surfaceRaised, overflow: "hidden" }}>
                    <div style={{
                      height: "100%", borderRadius: 4, width: `${(barW / 16) * 100}%`,
                      background: `linear-gradient(90deg, ${C.teal}, ${C.accent})`,
                    }} />
                  </div>
                  <span style={{ color: C.ink, width: 30, textAlign: "right" }}>{Math.round(barW)}</span>
                </div>
              );
            })}
            <div style={{
              marginTop: 24, paddingTop: 22, borderTop: `1px solid ${C.line}`,
              opacity: interpolate(frame, [92, 108], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
            }}>
              <div style={{ color: C.accent }}>✓ 2 endpoint bundles built</div>
              <div style={{ color: C.accent, marginTop: 10 }}>✓ 8 integration signals found</div>
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
