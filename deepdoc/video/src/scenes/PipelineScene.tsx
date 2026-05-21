import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F } from "../constants";

const PHASES = [
  {
    num: "01",
    name: "Scan",
    desc: "Parse source files. Detect endpoints, runtime surfaces, integrations, and OpenAPI specs. No LLM calls.",
    color: "#00E5FF",
  },
  {
    num: "02",
    name: "Plan",
    desc: "Multi-step LLM planner. Classify the repo, propose buckets, assign files, symbols, and artifacts.",
    color: "#7C6AFF",
  },
  {
    num: "03",
    name: "Generate",
    desc: "Build evidence packs per bucket. LLM call in parallel batches. MDX compile-check before write.",
    color: "#00E5A0",
  },
  {
    num: "04",
    name: "API Ref",
    desc: "Stage OpenAPI assets into Fumadocs /api/* pages when a spec is present in the repo.",
    color: "#FF9E00",
  },
  {
    num: "05",
    name: "Build",
    desc: "Write the Fumadocs site scaffold, page tree, search route, nav, and optional AI chatbot widget.",
    color: "#FF5F87",
  },
] as const;

const ENTER_DURATION = 30;
const PHASE_ACTIVE_DURATION = 84; // 2.8 s per phase
const FADE_OUT_START = 450;

export const PipelineScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 24], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [FADE_OUT_START, 480], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const headerSpring = spring({ frame, fps, config: { damping: 15, stiffness: 120 } });

  const activePhase = Math.min(
    PHASES.length - 1,
    Math.max(0, Math.floor((frame - ENTER_DURATION) / PHASE_ACTIVE_DURATION))
  );

  return (
    <AbsoluteFill
      style={{
        background: C.bg,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 72px",
        opacity,
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 56, textAlign: "center" }}>
        <div
          style={{
            fontFamily: F.mono,
            fontSize: 13,
            color: C.inkFaint,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            marginBottom: 18,
            opacity: fadeIn,
          }}
        >
          Pipeline
        </div>
        <h2
          style={{
            fontFamily: F.sans,
            fontSize: 58,
            fontWeight: 700,
            color: C.ink,
            margin: 0,
            letterSpacing: "-0.03em",
            opacity: headerSpring,
            transform: `translateY(${(1 - headerSpring) * 30}px)`,
          }}
        >
          Five phases. No magic.
        </h2>
      </div>

      {/* Phase cards */}
      <div
        style={{
          display: "flex",
          gap: 14,
          width: "100%",
          maxWidth: 1776,
          alignItems: "stretch",
        }}
      >
        {PHASES.map((phase, i) => {
          const cardSpring = spring({
            frame: Math.max(0, frame - i * 10),
            fps,
            config: { damping: 15, stiffness: 120 },
          });

          const isActive = i === activePhase && frame >= ENTER_DURATION;
          const isPast = i < activePhase && frame >= ENTER_DURATION;

          const activationProgress = isActive
            ? interpolate(
                frame - ENTER_DURATION - i * PHASE_ACTIVE_DURATION,
                [0, 12],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              )
            : 0;

          const phaseProgress = isActive
            ? (frame - ENTER_DURATION - i * PHASE_ACTIVE_DURATION) / PHASE_ACTIVE_DURATION
            : 0;

          return (
            <div
              key={phase.num}
              style={{
                flex: 1,
                borderRadius: 20,
                border: `1px solid ${isActive ? phase.color : isPast ? `${phase.color}50` : C.lineStrong}`,
                background: C.surface,
                padding: "28px 22px 26px",
                display: "flex",
                flexDirection: "column",
                gap: 11,
                transform: `translateY(${(1 - cardSpring) * 44}px)`,
                opacity: cardSpring * (isPast ? 0.65 : 1),
                boxShadow: isActive
                  ? `0 0 48px ${phase.color}22, inset 0 0 48px ${phase.color}0a`
                  : "none",
                position: "relative",
                overflow: "hidden",
              }}
            >
              {/* Active radial glow */}
              {isActive && (
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    background: `radial-gradient(ellipse 90% 50% at 50% 0%, ${phase.color}12, transparent 70%)`,
                    opacity: activationProgress,
                    pointerEvents: "none",
                  }}
                />
              )}

              {/* Step number */}
              <div
                style={{
                  fontFamily: F.mono,
                  fontSize: 13,
                  color: isActive ? phase.color : C.inkFaint,
                  letterSpacing: "0.1em",
                  transition: "none",
                }}
              >
                {phase.num}
              </div>

              {/* Phase name */}
              <div
                style={{
                  fontFamily: F.sans,
                  fontSize: 22,
                  fontWeight: 700,
                  color: isActive ? C.ink : isPast ? C.inkMuted : C.inkMuted,
                  letterSpacing: "-0.025em",
                }}
              >
                {phase.name}
              </div>

              {/* Description */}
              <div
                style={{
                  fontFamily: F.sans,
                  fontSize: 14,
                  lineHeight: 1.65,
                  color: isActive ? C.inkMuted : C.inkFaint,
                  flexGrow: 1,
                }}
              >
                {phase.desc}
              </div>

              {/* Progress bar at bottom */}
              {isActive && (
                <div
                  style={{
                    position: "absolute",
                    bottom: 0,
                    left: 0,
                    height: 2,
                    width: `${Math.min(1, phaseProgress) * 100}%`,
                    background: phase.color,
                    borderRadius: "0 2px 0 0",
                  }}
                />
              )}

              {/* Past checkmark */}
              {isPast && (
                <div
                  style={{
                    position: "absolute",
                    bottom: 0,
                    left: 0,
                    height: 2,
                    width: "100%",
                    background: `${phase.color}40`,
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
