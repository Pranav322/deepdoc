import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F } from "../constants";

const COMMAND = "$ deepdoc generate";

const OUTPUT: Array<{ text: string; startFrame: number; color: string }> = [
  { text: "  Scanning 847 source files...",          startFrame: 54,  color: C.inkMuted },
  { text: "  Building call graph + topology...",     startFrame: 72,  color: C.inkMuted },
  { text: "  Planning documentation structure...",   startFrame: 88,  color: C.inkMuted },
  { text: "  Generating 47 pages (batched)...",      startFrame: 104, color: C.inkMuted },
  { text: "  Building Fumadocs site + search...",    startFrame: 124, color: C.inkMuted },
  { text: "",                                        startFrame: 140, color: C.inkFaint },
  { text: "✓  47 pages generated in 1m 12s",         startFrame: 145, color: C.accent   },
  { text: "✓  Chatbot index built  (1,247 chunks)",  startFrame: 160, color: C.accent   },
  { text: "",                                        startFrame: 170, color: C.inkFaint },
  { text: "   Docs → http://localhost:3000",         startFrame: 174, color: C.inkFaint },
  { text: "   Chat → http://localhost:3000/ask",     startFrame: 186, color: C.inkFaint },
];

export const TerminalScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [185, 210], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const windowSpring = spring({ frame, fps, config: { damping: 13, stiffness: 105, mass: 0.9 } });

  const charsToShow = Math.floor(
    interpolate(frame, [18, 46], [0, COMMAND.length], {
      extrapolateLeft: "clamp", extrapolateRight: "clamp",
    })
  );
  const displayCommand = COMMAND.slice(0, charsToShow);
  const cursorVisible  = frame < 50 || Math.floor(frame / 15) % 2 === 0;

  // Glow pulse when done (frames 145+)
  const doneGlow = interpolate(frame, [145, 165], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ background: C.bg, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity }}>

      {/* Ambient glow when complete */}
      {doneGlow > 0 && (
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          background: `radial-gradient(ellipse 55% 45% at 50% 55%, ${C.accentGlow} 0%, transparent 70%)`,
          opacity: doneGlow * 0.5,
        }} />
      )}

      {/* Label */}
      <div style={{
        fontFamily: F.mono, fontSize: 13, color: C.inkFaint,
        letterSpacing: "0.18em", textTransform: "uppercase",
        marginBottom: 32, opacity: fadeIn,
      }}>
        One command
      </div>

      {/* Terminal window */}
      <div style={{
        width: 940, borderRadius: 18,
        border: `1px solid ${doneGlow > 0 ? `rgba(194,255,77,${doneGlow * 0.3})` : C.lineStrong}`,
        background: C.surface, overflow: "hidden",
        transform: `translateY(${(1 - windowSpring) * 52}px) scale(${0.93 + windowSpring * 0.07})`,
        boxShadow: doneGlow > 0
          ? `0 48px 100px rgba(0,0,0,0.7), 0 0 80px ${C.accent}${Math.round(doneGlow * 25).toString(16).padStart(2, "0")}`
          : "0 48px 100px rgba(0,0,0,0.7)",
      }}>
        {/* Title bar */}
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          borderBottom: `1px solid ${C.line}`,
          padding: "13px 18px",
        }}>
          <div style={{ display: "flex", gap: 7 }}>
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: "rgba(255,95,86,0.75)" }} />
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: "rgba(255,189,46,0.75)" }} />
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: "rgba(39,201,63,0.75)" }} />
          </div>
          <span style={{
            margin: "0 auto", fontFamily: F.mono, fontSize: 12, color: C.inkFaint,
          }}>
            zsh — deepdoc
          </span>
        </div>

        {/* Body */}
        <div style={{
          padding: "24px 30px 30px", fontFamily: F.mono,
          fontSize: 17, lineHeight: 1.9, color: C.ink, minHeight: 300,
        }}>
          <div>
            {displayCommand}
            {cursorVisible && (
              <span style={{
                display: "inline-block", width: 10, height: 20,
                background: C.accent, marginLeft: 2, verticalAlign: "middle", opacity: 0.9,
              }} />
            )}
          </div>

          {OUTPUT.map((line, i) => {
            if (frame < line.startFrame) return null;
            const lo = interpolate(frame, [line.startFrame, line.startFrame + 8], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            return (
              <div key={i} style={{ color: line.color, opacity: lo }}>
                {line.text}
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
