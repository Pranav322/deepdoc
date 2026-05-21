import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F } from "../constants";

const TAGS = ["Python 3.10+", "Node 18+", "MIT License"];

export const Outro = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 25], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [120, 150], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const titleSpring = spring({ frame, fps, config: { damping: 14, stiffness: 120 } });
  const cmdSpring = spring({ frame: Math.max(0, frame - 18), fps, config: { damping: 15, stiffness: 115 } });
  const tagsSpring = spring({ frame: Math.max(0, frame - 34), fps, config: { damping: 16, stiffness: 120 } });

  return (
    <AbsoluteFill
      style={{
        background: C.bg,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        opacity,
      }}
    >
      {/* Grid */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `
            linear-gradient(${C.line} 1px, transparent 1px),
            linear-gradient(90deg, ${C.line} 1px, transparent 1px)
          `,
          backgroundSize: "56px 56px",
          WebkitMaskImage:
            "radial-gradient(ellipse 70% 60% at 50% 50%, black 30%, transparent 100%)",
          maskImage:
            "radial-gradient(ellipse 70% 60% at 50% 50%, black 30%, transparent 100%)",
          opacity: 0.6,
        }}
      />

      {/* Domain */}
      <h2
        style={{
          fontFamily: F.sans,
          fontSize: 88,
          fontWeight: 700,
          letterSpacing: "-0.04em",
          margin: "0 0 14px",
          textAlign: "center",
          background: "linear-gradient(135deg, #ffffff 20%, #00E5FF 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
          opacity: titleSpring,
          transform: `translateY(${(1 - titleSpring) * 44}px)`,
        }}
      >
        deepdoc.dev
      </h2>

      {/* Install command */}
      <div
        style={{
          fontFamily: F.mono,
          fontSize: 22,
          color: C.accent,
          marginBottom: 52,
          opacity: cmdSpring,
          transform: `translateY(${(1 - cmdSpring) * 22}px)`,
          letterSpacing: "0.01em",
        }}
      >
        pip install deepdoc
      </div>

      {/* Tags */}
      <div
        style={{
          display: "flex",
          gap: 12,
          opacity: tagsSpring,
          transform: `translateY(${(1 - tagsSpring) * 18}px)`,
        }}
      >
        {TAGS.map((tag) => (
          <span
            key={tag}
            style={{
              border: `1px solid ${C.lineStrong}`,
              borderRadius: 100,
              padding: "7px 20px",
              fontFamily: F.sans,
              fontSize: 15,
              color: C.inkMuted,
            }}
          >
            {tag}
          </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
