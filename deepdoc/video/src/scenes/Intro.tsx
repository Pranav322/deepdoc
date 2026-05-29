import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F } from "../constants";

export const Intro = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [90, 120], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const titleSpring = spring({ frame, fps, config: { damping: 14, stiffness: 120, mass: 0.9 } });
  const tagSpring = spring({ frame: Math.max(0, frame - 8), fps, config: { damping: 16, stiffness: 130 } });
  const subtitleSpring = spring({ frame: Math.max(0, frame - 22), fps, config: { damping: 16, stiffness: 110 } });

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
      {/* Subtle grid texture */}
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
            "radial-gradient(ellipse 70% 60% at 50% 40%, black 30%, transparent 100%)",
          maskImage:
            "radial-gradient(ellipse 70% 60% at 50% 40%, black 30%, transparent 100%)",
          opacity: 0.6,
        }}
      />

      {/* Version badge */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          border: `1px solid ${C.lineStrong}`,
          background: `${C.surface}cc`,
          borderRadius: 100,
          padding: "7px 18px",
          marginBottom: 38,
          fontFamily: F.mono,
          fontSize: 15,
          color: C.inkMuted,
          letterSpacing: "0.02em",
          opacity: tagSpring,
          transform: `translateY(${(1 - tagSpring) * 20}px)`,
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: C.accent,
            boxShadow: `0 0 10px ${C.accent}`,
            display: "inline-block",
          }}
        />
        v2.3 · MDX-safe generation · One-key chatbot
      </div>

      {/* Main title */}
      <h1
        style={{
          fontFamily: F.sans,
          fontSize: 128,
          fontWeight: 700,
          letterSpacing: "-0.045em",
          lineHeight: 1,
          margin: 0,
          textAlign: "center",
          background: "linear-gradient(135deg, #ffffff 20%, #00E5FF 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
          opacity: titleSpring,
          transform: `translateY(${(1 - titleSpring) * 50}px)`,
        }}
      >
        DeepDoc
      </h1>

      {/* Tagline */}
      <p
        style={{
          fontFamily: F.sans,
          fontSize: 30,
          fontWeight: 400,
          color: C.inkMuted,
          textAlign: "center",
          margin: "24px 0 0",
          maxWidth: 800,
          lineHeight: 1.45,
          opacity: subtitleSpring * fadeIn,
          transform: `translateY(${(1 - subtitleSpring) * 28}px)`,
        }}
      >
        Engineering docs your team will{" "}
        <span style={{ color: C.ink, fontWeight: 500 }}>actually read.</span>
      </p>
    </AbsoluteFill>
  );
};
