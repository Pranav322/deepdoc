import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F } from "../constants";

export const ResultScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 28], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [150, 180], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const headingSpring = spring({ frame, fps, config: { damping: 15, stiffness: 120 } });
  const leftSpring = spring({ frame: Math.max(0, frame - 12), fps, config: { damping: 14, stiffness: 100 } });
  const rightSpring = spring({ frame: Math.max(0, frame - 20), fps, config: { damping: 14, stiffness: 100 } });

  // Counting animations
  const pagesCount = Math.floor(
    interpolate(frame, [28, 90], [0, 47], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
  );
  const chunksCount = Math.floor(
    interpolate(frame, [50, 130], [0, 1247], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
  );
  const timeMs = interpolate(frame, [28, 90], [0, 72], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const timeDisplay = `${Math.floor(timeMs / 60)}m ${Math.floor(timeMs % 60)}s`;

  return (
    <AbsoluteFill
      style={{
        background: C.bg,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 100px",
        opacity,
      }}
    >
      <div
        style={{
          fontFamily: F.mono,
          fontSize: 13,
          color: C.inkFaint,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          marginBottom: 20,
          opacity: fadeIn,
        }}
      >
        Result
      </div>

      <h2
        style={{
          fontFamily: F.sans,
          fontSize: 50,
          fontWeight: 700,
          color: C.ink,
          margin: "0 0 60px",
          textAlign: "center",
          letterSpacing: "-0.03em",
          opacity: headingSpring,
          transform: `translateY(${(1 - headingSpring) * 28}px)`,
        }}
      >
        A site. A chatbot. Grounded in your source.
      </h2>

      <div style={{ display: "flex", gap: 20, width: "100%", maxWidth: 1200 }}>
        {/* Docs card */}
        <div
          style={{
            flex: 1,
            border: `1px solid ${C.accent}50`,
            borderRadius: 22,
            background: C.surface,
            padding: "40px 44px",
            display: "flex",
            flexDirection: "column",
            gap: 10,
            transform: `translateX(${(1 - leftSpring) * -50}px)`,
            opacity: leftSpring,
            boxShadow: `0 0 60px ${C.accent}12`,
          }}
        >
          <div style={{ fontFamily: F.mono, fontSize: 13, color: C.accent, letterSpacing: "0.08em" }}>
            Docs site
          </div>
          <div
            style={{
              fontFamily: F.sans,
              fontSize: 84,
              fontWeight: 700,
              color: C.ink,
              lineHeight: 1,
              letterSpacing: "-0.05em",
            }}
          >
            {pagesCount}
          </div>
          <div style={{ fontFamily: F.sans, fontSize: 18, color: C.inkMuted }}>
            MDX pages generated
          </div>
          <div
            style={{
              fontFamily: F.sans,
              fontSize: 15,
              color: C.inkFaint,
              marginTop: 4,
            }}
          >
            in {timeDisplay}
          </div>
          <div
            style={{
              marginTop: 20,
              padding: "11px 16px",
              background: C.bg,
              borderRadius: 10,
              border: `1px solid ${C.line}`,
              fontFamily: F.mono,
              fontSize: 14,
              color: C.inkFaint,
            }}
          >
            → localhost:3000
          </div>
        </div>

        {/* Chatbot card */}
        <div
          style={{
            flex: 1,
            border: `1px solid rgba(124,106,255,0.4)`,
            borderRadius: 22,
            background: C.surface,
            padding: "40px 44px",
            display: "flex",
            flexDirection: "column",
            gap: 10,
            transform: `translateX(${(1 - rightSpring) * 50}px)`,
            opacity: rightSpring,
            boxShadow: "0 0 60px rgba(124,106,255,0.1)",
          }}
        >
          <div style={{ fontFamily: F.mono, fontSize: 13, color: "#7C6AFF", letterSpacing: "0.08em" }}>
            AI Chatbot
          </div>
          <div
            style={{
              fontFamily: F.sans,
              fontSize: 84,
              fontWeight: 700,
              color: C.ink,
              lineHeight: 1,
              letterSpacing: "-0.05em",
            }}
          >
            {chunksCount.toLocaleString()}
          </div>
          <div style={{ fontFamily: F.sans, fontSize: 18, color: C.inkMuted }}>
            chunks indexed
          </div>
          <div
            style={{
              fontFamily: F.sans,
              fontSize: 15,
              color: C.inkFaint,
              marginTop: 4,
            }}
          >
            evidence-grounded answers
          </div>
          <div
            style={{
              marginTop: 20,
              padding: "11px 16px",
              background: C.bg,
              borderRadius: 10,
              border: `1px solid ${C.line}`,
              fontFamily: F.mono,
              fontSize: 14,
              color: C.inkFaint,
            }}
          >
            → localhost:3000/ask
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
