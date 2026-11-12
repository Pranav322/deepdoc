import { interpolate, useCurrentFrame } from "remotion";
import { C, F } from "../constants";

export type Cue = { from: number; to: number; index?: string; title: string; note?: string };

/** A lower-third that changes with the action: number, phase, one fact. */
export const Caption = ({ cues }: { cues: Cue[] }) => {
  const frame = useCurrentFrame();
  const cue = cues.find((c) => frame >= c.from && frame < c.to);
  if (!cue) return null;
  const inP = interpolate(frame, [cue.from, cue.from + 10], [0, 1], { extrapolateRight: "clamp" });
  const outP = interpolate(frame, [cue.to - 8, cue.to], [1, 0], { extrapolateLeft: "clamp" });
  const o = Math.min(inP, outP);
  return (
    <div style={{ position: "absolute", left: 96, bottom: 54, display: "flex", alignItems: "baseline", gap: 18, opacity: o, transform: `translateY(${(1 - inP) * 10}px)` }}>
      {cue.index && <span style={{ fontFamily: F.mono, fontSize: 20, color: C.accent }}>{cue.index}</span>}
      <span style={{ fontFamily: F.sans, fontSize: 30, fontWeight: 600, letterSpacing: "-0.025em", color: C.ink }}>{cue.title}</span>
      {cue.note && <span style={{ fontFamily: F.mono, fontSize: 18, color: C.inkFaint }}>{cue.note}</span>}
    </div>
  );
};
