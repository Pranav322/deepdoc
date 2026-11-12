import { AbsoluteFill, random, useCurrentFrame } from "remotion";
import { C } from "../constants";

const CELL = 24;
const COLS = Math.ceil(1920 / CELL);
const ROWS = Math.ceil(1080 / CELL);
const SPARKS = 46;
const LIFE = 70; // frames a spark stays lit

/**
 * The site's pixel grid: fine lines, and cells that light up briefly in the
 * accent's tonal ramp. Deterministic (seeded), so every render is identical.
 */
export const Backdrop = () => {
  const frame = useCurrentFrame();
  const cells = [];
  for (let i = 0; i < SPARKS; i++) {
    const period = LIFE + Math.floor(random(`p${i}`) * 220);
    const offset = Math.floor(random(`o${i}`) * period);
    const cycle = Math.floor((frame + offset) / period);
    const t = (frame + offset) % period;
    if (t > LIFE) continue;
    const x = Math.floor(random(`x${i}-${cycle}`) * COLS);
    const y = Math.floor(random(`y${i}-${cycle}`) * ROWS);
    const tone = C.ramp[Math.floor(random(`c${i}-${cycle}`) * C.ramp.length)];
    const alpha = Math.sin((t / LIFE) * Math.PI) * 0.55;
    cells.push(
      <div key={i} style={{ position: "absolute", left: x * CELL + 1, top: y * CELL + 1, width: CELL - 1, height: CELL - 1, background: tone, opacity: alpha }} />
    );
  }
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${C.grid} 1px, transparent 1px), linear-gradient(90deg, ${C.grid} 1px, transparent 1px)`,
          backgroundSize: `${CELL}px ${CELL}px`,
        }}
      />
      {cells}
      {/* Keeps the eye on the centre and the edges quiet. */}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 75% 70% at 50% 50%, transparent 40%, rgba(13,13,12,0.85) 100%)" }} />
    </AbsoluteFill>
  );
};
