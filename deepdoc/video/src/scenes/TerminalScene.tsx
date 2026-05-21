import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F } from "../constants";

const COMMAND = "$ deepdoc generate";

const OUTPUT: Array<{ text: string; startFrame: number; color: string }> = [
  { text: "  Scanning 847 source files...",         startFrame: 55,  color: C.inkMuted },
  { text: "  Planning documentation structure...",  startFrame: 78,  color: C.inkMuted },
  { text: "  Generating 47 pages (batched)...",     startFrame: 100, color: C.inkMuted },
  { text: "  Building Fumadocs site...",            startFrame: 122, color: C.inkMuted },
  { text: "",                                       startFrame: 140, color: C.inkFaint },
  { text: "✓  47 pages generated in 1m 12s",        startFrame: 145, color: C.accent   },
  { text: "✓  Chatbot index built  (1,247 chunks)", startFrame: 162, color: C.accent   },
  { text: "",                                       startFrame: 172, color: C.inkFaint },
  { text: "   Docs → http://localhost:3000",        startFrame: 175, color: C.inkFaint },
  { text: "   Chat → http://localhost:3000/ask",    startFrame: 186, color: C.inkFaint },
];

export const TerminalScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [210, 240], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const windowSpring = spring({ frame, fps, config: { damping: 14, stiffness: 110, mass: 0.9 } });

  const charsToShow = Math.floor(
    interpolate(frame, [16, 48], [0, COMMAND.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })
  );
  const displayCommand = COMMAND.slice(0, charsToShow);
  const cursorVisible = frame < 52 || Math.floor(frame / 15) % 2 === 0;

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
      {/* Label */}
      <div
        style={{
          fontFamily: F.mono,
          fontSize: 13,
          color: C.inkFaint,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          marginBottom: 32,
          opacity: fadeIn,
        }}
      >
        One command
      </div>

      {/* Terminal window */}
      <div
        style={{
          width: 920,
          borderRadius: 18,
          border: `1px solid ${C.lineStrong}`,
          background: C.surface,
          overflow: "hidden",
          transform: `translateY(${(1 - windowSpring) * 48}px) scale(${0.94 + windowSpring * 0.06})`,
          boxShadow: "0 48px 96px rgba(0,0,0,0.7)",
        }}
      >
        {/* Title bar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            borderBottom: `1px solid ${C.line}`,
            padding: "13px 18px",
          }}
        >
          <div style={{ display: "flex", gap: 7 }}>
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: "rgba(255,95,86,0.7)" }} />
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: "rgba(255,189,46,0.7)" }} />
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: "rgba(39,201,63,0.7)" }} />
          </div>
          <span
            style={{
              margin: "0 auto",
              fontFamily: F.mono,
              fontSize: 12,
              color: C.inkFaint,
            }}
          >
            bash — deepdoc
          </span>
        </div>

        {/* Body */}
        <div
          style={{
            padding: "22px 28px 28px",
            fontFamily: F.mono,
            fontSize: 17,
            lineHeight: 1.9,
            color: C.ink,
            minHeight: 300,
          }}
        >
          {/* Command line */}
          <div>
            {displayCommand}
            {cursorVisible && (
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 20,
                  background: C.accent,
                  marginLeft: 2,
                  verticalAlign: "middle",
                  opacity: 0.85,
                }}
              />
            )}
          </div>

          {/* Output lines */}
          {OUTPUT.map((line, i) => {
            if (frame < line.startFrame) return null;
            const lineOpacity = interpolate(frame, [line.startFrame, line.startFrame + 8], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div key={i} style={{ color: line.color, opacity: lineOpacity }}>
                {line.text}
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
