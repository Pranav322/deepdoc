import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F, SPRING } from "../constants";

const WORDS = ["Documentation", "that", "keeps", "pace", "with", "your"];
const D = "M14 9 H24 A15 15 0 0 1 24 39 H14";

export const Outro = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rise = (delay: number) => {
    const p = spring({ frame: frame - delay, fps, config: SPRING.soft });
    return { opacity: p, transform: `translateY(${(1 - p) * 26}px)` };
  };
  const word = (i: number) => {
    const p = interpolate(frame, [18 + i * 3, 34 + i * 3], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return { display: "inline-block", marginRight: "0.24em", opacity: p, transform: `translateY(${(1 - p) * 0.4}em)`, filter: `blur(${(1 - p) * 10}px)` } as const;
  };
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column" }}>
      <div style={{ ...rise(4), display: "flex", alignItems: "center", fontFamily: F.sans, fontSize: 46, fontWeight: 600, letterSpacing: "-0.015em", color: C.ink }}>
        <svg width="62" height="62" viewBox="0 0 48 48" fill="none" style={{ marginRight: 2, marginLeft: -16 }}>
          <path d={D} transform="translate(6 6)" stroke={C.accent} strokeWidth="2" opacity="0.18" />
          <path d={D} transform="translate(3 3)" stroke={C.accent} strokeWidth="2" opacity="0.4" />
          <path fillRule="evenodd" fill={C.accent} d="M14 9 H24 A15 15 0 0 1 24 39 H14 Z M20 15 H24 A9 9 0 0 1 24 33 H20 Z" />
        </svg>
        eepDoc
      </div>
      <div style={{ marginTop: 34, maxWidth: 1300, textAlign: "center", fontFamily: F.sans, fontSize: 104, fontWeight: 600, letterSpacing: "-0.045em", lineHeight: 1.02, color: C.ink }}>
        {WORDS.map((w, i) => <span key={w} style={word(i)}>{w}</span>)}
        <span style={{ ...word(WORDS.length), marginRight: 0, fontFamily: F.serif, fontStyle: "italic", fontWeight: 400, letterSpacing: "-0.02em", fontSize: "1.06em", color: C.accent }}>codebase.</span>
      </div>
      <div style={{ ...rise(46), marginTop: 56, display: "flex", alignItems: "center", gap: 22 }}>
        <div style={{ padding: "16px 26px", borderRadius: 12, background: C.surface, border: `1px solid ${C.lineStrong}`, fontFamily: F.mono, fontSize: 28, color: C.ink }}>
          <span style={{ color: C.accent }}>$ </span>pip install deepdoc
        </div>
        <span style={{ fontFamily: F.mono, fontSize: 24, color: C.inkFaint }}>deepdoc.tech</span>
      </div>
    </AbsoluteFill>
  );
};
