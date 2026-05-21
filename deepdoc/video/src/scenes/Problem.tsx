import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F } from "../constants";

export const Problem = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [90, 120], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const line1 = spring({ frame, fps, config: { damping: 16, stiffness: 130 } });
  const line2 = spring({ frame: Math.max(0, frame - 28), fps, config: { damping: 16, stiffness: 130 } });
  const line3 = spring({ frame: Math.max(0, frame - 52), fps, config: { damping: 16, stiffness: 130 } });

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
      <div style={{ textAlign: "center", maxWidth: 960 }}>
        <p
          style={{
            fontFamily: F.sans,
            fontSize: 56,
            fontWeight: 600,
            color: C.inkMuted,
            margin: "0 0 6px",
            letterSpacing: "-0.025em",
            opacity: line1,
            transform: `translateY(${(1 - line1) * 32}px)`,
          }}
        >
          Your codebase grows.
        </p>

        <p
          style={{
            fontFamily: F.sans,
            fontSize: 56,
            fontWeight: 700,
            color: C.ink,
            margin: "0 0 52px",
            letterSpacing: "-0.025em",
            opacity: line2,
            transform: `translateY(${(1 - line2) * 32}px)`,
          }}
        >
          Docs don't.
        </p>

        <p
          style={{
            fontFamily: F.sans,
            fontSize: 22,
            fontWeight: 400,
            color: C.inkFaint,
            margin: 0,
            lineHeight: 1.65,
            letterSpacing: "-0.01em",
            opacity: line3,
            transform: `translateY(${(1 - line3) * 20}px)`,
          }}
        >
          New teammates onboard from Slack. Endpoints get reversed-engineered.
          <br />
          Architecture only lives in someone's head.
        </p>
      </div>
    </AbsoluteFill>
  );
};
