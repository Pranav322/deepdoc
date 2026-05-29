import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F } from "../constants";

const PHASES = [
  { num: "01", name: "Scan",     color: C.blue,   icon: "⬡" },
  { num: "02", name: "Plan",     color: C.purple,  icon: "◈" },
  { num: "03", name: "Generate", color: C.teal,    icon: "◎" },
  { num: "04", name: "API Ref",  color: C.orange,  icon: "◇" },
  { num: "05", name: "Build",    color: C.pink,    icon: "◉" },
] as const;

const PHASE_DESCS = [
  "Parse source files.\nDetect endpoints, integrations,\nOpenAPI specs. No LLM calls.",
  "Multi-step LLM planner.\nClassify repo, propose buckets,\nassign files and symbols.",
  "Build evidence packs per bucket.\nLLM in parallel batches.\nPython-side MDX repair.",
  "Stage OpenAPI assets into\nFumadocs /api/* pages\nwhen a spec is present.",
  "Write Fumadocs scaffold,\npage tree, search route,\nand AI chatbot widget.",
];

// Each phase is active for 30 frames; connector lines animate between them
const PHASE_FRAMES = 30;
const ENTER = 24;

export const PipelineScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 22], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [188, 210], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const headerSpring = spring({ frame, fps, config: { damping: 14, stiffness: 115 } });

  // Which phase is active (0-4)
  const activePhaseF = Math.max(0, (frame - ENTER) / PHASE_FRAMES);
  const activePhase  = Math.min(PHASES.length - 1, Math.floor(activePhaseF));

  // All done when past last phase
  const allDone = frame >= ENTER + PHASES.length * PHASE_FRAMES;

  // Description fade
  const descOpacity = interpolate(frame, [ENTER + 6, ENTER + 22], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{
      background: C.bg, opacity,
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
      padding: "0 80px",
    }}>

      {/* Header */}
      <div style={{ marginBottom: 64, textAlign: "center" }}>
        <div style={{
          fontFamily: F.mono, fontSize: 13, color: C.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
          marginBottom: 16, opacity: fadeIn,
        }}>
          Pipeline
        </div>
        <h2 style={{
          fontFamily: F.sans, fontSize: 60, fontWeight: 800,
          color: C.ink, margin: 0, letterSpacing: "-0.035em",
          opacity: headerSpring,
          transform: `translateY(${(1 - headerSpring) * 32}px)`,
        }}>
          Five phases.{" "}
          <span style={{
            background: `linear-gradient(135deg, ${C.accent} 0%, ${C.teal} 100%)`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          }}>
            No magic.
          </span>
        </h2>
      </div>

      {/* ── Flow diagram ─────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "flex-start", width: "100%", maxWidth: 1600, position: "relative" }}>
        {PHASES.map((phase, i) => {
          const nodeSpring = spring({
            frame: Math.max(0, frame - i * 8),
            fps, config: { damping: 14, stiffness: 120 },
          });

          const isActive = i === activePhase && !allDone;
          const isPast   = i < activePhase || allDone;

          // Progress within this phase (0→1)
          const phaseProgress = isActive
            ? Math.min(1, (frame - ENTER - i * PHASE_FRAMES) / PHASE_FRAMES)
            : isPast ? 1 : 0;

          // Connector line between nodes
          const connectorProgress = i < PHASES.length - 1
            ? (() => {
                const connStart = ENTER + (i + 1) * PHASE_FRAMES - 18;
                return Math.min(1, Math.max(0, (frame - connStart) / 18));
              })()
            : 0;

          const activeScale = isActive
            ? 1 + Math.sin(phaseProgress * Math.PI) * 0.06
            : 1;

          return (
            <div key={phase.num} style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              position: "relative",
              opacity: nodeSpring,
              transform: `translateY(${(1 - nodeSpring) * 40}px)`,
            }}>
              {/* Connecting line to next node */}
              {i < PHASES.length - 1 && (
                <div style={{
                  position: "absolute",
                  top: 40, left: "50%", height: 2,
                  width: "100%",
                  background: C.lineStrong,
                  zIndex: 0,
                }}>
                  {/* Animated fill */}
                  <div style={{
                    position: "absolute", top: 0, left: 0, height: "100%",
                    width: `${connectorProgress * 100}%`,
                    background: `linear-gradient(90deg, ${PHASES[i].color}, ${PHASES[i + 1].color})`,
                    transition: "none",
                  }} />
                  {/* Traveling dot */}
                  {connectorProgress > 0 && connectorProgress < 1 && (
                    <div style={{
                      position: "absolute", top: "50%",
                      left: `${connectorProgress * 100}%`,
                      transform: "translate(-50%, -50%)",
                      width: 8, height: 8, borderRadius: "50%",
                      background: PHASES[i + 1].color,
                      boxShadow: `0 0 12px ${PHASES[i + 1].color}`,
                    }} />
                  )}
                </div>
              )}

              {/* Node circle */}
              <div style={{
                position: "relative", zIndex: 1,
                width: 80, height: 80, borderRadius: "50%",
                border: `2px solid ${isPast || isActive ? phase.color : C.lineStrong}`,
                background: isPast || isActive
                  ? `radial-gradient(circle, ${phase.color}22 0%, ${C.surface} 70%)`
                  : C.surface,
                display: "flex", alignItems: "center", justifyContent: "center",
                transform: `scale(${activeScale})`,
                boxShadow: isActive
                  ? `0 0 36px ${phase.color}55, 0 0 72px ${phase.color}22`
                  : isPast ? `0 0 16px ${phase.color}30` : "none",
              }}>
                <span style={{
                  fontFamily: F.mono, fontSize: 22,
                  color: isPast || isActive ? phase.color : C.inkFaint,
                }}>
                  {isPast && !isActive ? "✓" : phase.num}
                </span>

                {/* Progress ring */}
                {isActive && (
                  <svg style={{ position: "absolute", inset: -3, width: 86, height: 86 }}>
                    <circle
                      cx="43" cy="43" r="40"
                      fill="none"
                      stroke={phase.color}
                      strokeWidth="2"
                      strokeDasharray={`${phaseProgress * 251} 251`}
                      strokeLinecap="round"
                      style={{ transform: "rotate(-90deg)", transformOrigin: "43px 43px" }}
                    />
                  </svg>
                )}
              </div>

              {/* Phase name */}
              <div style={{
                marginTop: 16, fontFamily: F.sans,
                fontSize: 18, fontWeight: 700,
                color: isPast || isActive ? C.ink : C.inkMuted,
                letterSpacing: "-0.02em",
                textAlign: "center",
              }}>
                {phase.name}
              </div>

              {/* Description — only show for active phase */}
              {isActive && (
                <div style={{
                  marginTop: 10, fontFamily: F.sans, fontSize: 13,
                  color: C.inkMuted, textAlign: "center",
                  lineHeight: 1.6, maxWidth: 200, whiteSpace: "pre-line",
                  opacity: descOpacity,
                }}>
                  {PHASE_DESCS[i]}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* All done badge */}
      {allDone && (
        <div style={{
          marginTop: 56,
          display: "flex", alignItems: "center", gap: 12,
          border: `1px solid ${C.accent}60`,
          background: `${C.accentDim}`,
          borderRadius: 100, padding: "10px 28px",
          fontFamily: F.sans, fontSize: 18, fontWeight: 600, color: C.accent,
          opacity: interpolate(frame, [ENTER + PHASES.length * PHASE_FRAMES, ENTER + PHASES.length * PHASE_FRAMES + 20], [0, 1], {
            extrapolateLeft: "clamp", extrapolateRight: "clamp",
          }),
          boxShadow: `0 0 40px ${C.accentGlow}`,
        }}>
          <span style={{
            width: 8, height: 8, borderRadius: "50%",
            background: C.accent, boxShadow: `0 0 10px ${C.accent}`,
            display: "inline-block",
          }} />
          Site ready · Chatbot indexed
        </div>
      )}
    </AbsoluteFill>
  );
};
