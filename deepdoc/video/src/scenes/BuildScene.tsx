import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F, SPRING } from "../constants";
import { BUILD_STATS, BUILD_TIMINGS } from "../data";

// Real "Phase 5/5: Building site" completion summary — the exact box the
// CLI prints when a run finishes.
export const BuildScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [118, 135], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const headerSpring = spring({ frame, fps, config: SPRING.soft });
  const cardSpring   = spring({ frame: Math.max(0, frame - 10), fps, config: SPRING.soft });

  return (
    <AbsoluteFill style={{
      background: C.bg, opacity,
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
      padding: "0 70px",
    }}>
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: `radial-gradient(ellipse 60% 50% at 50% 15%, ${C.accentDim} 0%, transparent 70%)`,
      }} />

      {/* Header */}
      <div style={{ marginBottom: 40, textAlign: "center" }}>
        <div style={{
          fontFamily: F.mono, fontSize: 14, color: C.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
          marginBottom: 16, opacity: fadeIn,
        }}>
          Phase 5 / 5 · Build
        </div>
        <h2 style={{
          fontFamily: F.sans, fontSize: 56, fontWeight: 800,
          color: C.ink, margin: 0, letterSpacing: "-0.035em",
          opacity: headerSpring,
          transform: `translateY(${(1 - headerSpring) * 26}px)`,
        }}>
          Then it hands you{" "}
          <span style={{
            background: `linear-gradient(135deg, ${C.accent}, ${C.teal})`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          }}>
            a finished site.
          </span>
        </h2>
      </div>

      {/* Big real completion card */}
      <div style={{
        width: "100%", maxWidth: 1660, borderRadius: 22,
        border: `1px solid ${C.accent}40`, background: C.surface,
        boxShadow: `0 0 90px ${C.accentDim}`,
        opacity: cardSpring, transform: `translateY(${(1 - cardSpring) * 26}px)`,
        overflow: "hidden",
      }}>
        {/* Top strip: scaffold + timings, straight from the real log */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "20px 36px", borderBottom: `1px solid ${C.line}`,
          background: C.surfaceRaised, fontFamily: F.mono, fontSize: 15,
        }}>
          <span style={{ color: C.accent }}>✓ Next.js site scaffold written</span>
          <span style={{ color: C.inkFaint, fontSize: 13 }}>{BUILD_TIMINGS}</span>
        </div>

        <div style={{ padding: "34px 40px 40px" }}>
          <div style={{
            fontFamily: F.sans, fontSize: 26, fontWeight: 700, color: C.accent,
            marginBottom: 26,
          }}>
            Documentation generated!
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18 }}>
            {BUILD_STATS.map((s, i) => {
              const start = 20 + i * 7;
              const so = interpolate(frame, [start, start + 14], [0, 1], {
                extrapolateLeft: "clamp", extrapolateRight: "clamp",
              });
              const shift = interpolate(frame, [start, start + 14], [16, 0], {
                extrapolateLeft: "clamp", extrapolateRight: "clamp",
              });
              const isStatus = s.label === "Status";
              return (
                <div key={s.label} style={{
                  border: `1px solid ${C.line}`, borderRadius: 14,
                  background: C.surfaceRaised, padding: "20px 22px",
                  opacity: so, transform: `translateY(${shift}px)`,
                }}>
                  <div style={{
                    fontFamily: F.sans, fontSize: 32, fontWeight: 800,
                    color: isStatus ? C.accent : C.ink, marginBottom: 6,
                    letterSpacing: "-0.02em",
                  }}>
                    {s.value}
                  </div>
                  <div style={{
                    fontFamily: F.mono, fontSize: 13, color: C.inkFaint,
                    letterSpacing: "0.03em",
                  }}>
                    {s.label}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Preview / Deploy — real CLI next-step commands */}
          <div style={{
            display: "flex", gap: 16, marginTop: 30,
            opacity: interpolate(frame, [92, 112], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}>
            {[
              { label: "Preview", cmd: "deepdoc serve" },
              { label: "Deploy", cmd: "deepdoc deploy" },
            ].map((a) => (
              <div key={a.cmd} style={{
                flex: 1, display: "flex", alignItems: "center", gap: 12,
                border: `1px solid ${C.lineStrong}`, borderRadius: 12,
                padding: "16px 22px", background: C.bg,
              }}>
                <span style={{ fontFamily: F.sans, fontSize: 13, color: C.inkFaint }}>{a.label}</span>
                <span style={{ fontFamily: F.mono, fontSize: 17, color: C.ink }}>{a.cmd}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
