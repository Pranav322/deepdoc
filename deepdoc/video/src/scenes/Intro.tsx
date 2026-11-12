import { AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F, SPRING, T } from "../constants";

// The hook. File names are real paths from the youtube-notes repository (the
// same files its generated docs cite); "56" is the real scan count from the
// run shown next (see data.ts). The line "Your codebase grows. The docs
// don't." is the whole pitch, so it comes first.
const FILES = [
  "backend/app/main.py", "backend/app/models.py", "backend/app/db.py", "backend/app/services/ai.py",
  "backend/app/services/transcript.py", "backend/pyproject.toml", "backend/requirements.txt", "backend/Dockerfile",
  "docker-compose.yml", "README.md", "frontend/app/page.tsx", "frontend/app/layout.tsx",
  "frontend/components/NoteInput.tsx", "frontend/components/NoteViewer.tsx", "frontend/components/NotesGallery.tsx",
  "frontend/lib/api.ts", "frontend/package.json", "frontend/tsconfig.json", "frontend/vercel.json", "frontend/Dockerfile",
  "frontend/app/api/[...path]/route.ts", "frontend/README.md",
];

const W = 1920, H = 1080, CX = W / 2, CY = H / 2;
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Seeded layout in six rows, three above the headline and three below, so the
// files frame the line instead of sitting behind it. Chips are packed by their
// measured width so they never overlap. Every render is identical.
const ROWS: { y: number; count: number; shift: number }[] = [
  { y: 168, count: 4, shift: -50 }, { y: 232, count: 4, shift: 70 }, { y: 296, count: 3, shift: -20 },
  { y: 790, count: 4, shift: 60 }, { y: 854, count: 4, shift: -60 }, { y: 918, count: 3, shift: 30 },
];
const widthOf = (name: string) => name.length * 10.9 + 52;
const GAP = 22;
let cursor = 0;
const chips = ROWS.flatMap((row, r) => {
  const names = FILES.slice(cursor, cursor + row.count);
  const total = names.reduce((sum, n) => sum + widthOf(n), 0) + GAP * (names.length - 1);
  let x = (W - total) / 2 + row.shift;
  return names.map((name) => {
    const i = cursor++;
    const left = x;
    x += widthOf(name) + GAP;
    const edge = Math.floor(random(`e${i}`) * 4);
    const far = 700 + random(`f${i}`) * 500;
    const from = [[-far, 0], [far, 0], [0, -far], [0, far]][edge];
    return { name, x: left, y: row.y + (random(`y${i}`) - 0.5) * 10, fromX: from[0], fromY: from[1], delay: 4 + Math.floor(random(`d${i}`) * 46), hot: i % 7 === 2, phase: random(`b${i}`) * 6.28 };
  });
});

const IN_END = 150; // chips converge and vanish; "One command." takes over

export const Intro = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const count = Math.round(interpolate(frame, [4, 64], [0, 56], { ...clamp, easing: Easing.out(Easing.cubic) }));
  const converge = interpolate(frame, [104, 138], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const exit = interpolate(frame, [T.INTRO - T.OVERLAP, T.INTRO], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });

  const word = (start: number, i: number) => {
    const p = interpolate(frame, [start + i * 5, start + i * 5 + 16], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
    return { display: "inline-block", marginRight: "0.24em", opacity: p, transform: `translateY(${(1 - p) * 0.45}em)`, filter: `blur(${(1 - p) * 12}px)` } as const;
  };

  const l1 = ["Your", "codebase", "grows."];
  const l2 = ["The", "docs", "don't."];
  const headOut = interpolate(frame, [96, 112], [1, 0], clamp);

  const oneIn = interpolate(frame, [118, 136], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const cmd = "deepdoc generate";
  const typed = cmd.slice(0, Math.max(0, Math.floor((frame - 134) / 1.6)));
  const caretOn = Math.floor(frame / 12) % 2 === 0;
  const cmdIn = spring({ frame: frame - 128, fps, config: SPRING.snappy });

  return (
    <AbsoluteFill style={{ opacity: 1 - exit, transform: `scale(${1 + exit * 0.04})`, filter: `blur(${exit * 8}px)` }}>
      {/* The files. */}
      {chips.map((c, i) => {
        const p = spring({ frame: frame - c.delay, fps, config: SPRING.soft });
        const bob = Math.sin(frame / 38 + c.phase) * 7;
        const cx = c.x + (1 - p) * c.fromX + (CX - c.x - 130) * converge;
        const cy = c.y + (1 - p) * c.fromY + bob * (1 - converge) + (CY - c.y - 18) * converge;
        const o = Math.min(1, p * 1.4) * (1 - converge) * 0.95;
        if (o <= 0.01) return null;
        return (
          <div
            key={c.name}
            style={{
              position: "absolute", left: cx, top: cy, display: "flex", alignItems: "center", gap: 10, padding: "9px 15px",
              borderRadius: 9, background: C.surface, border: `1px solid ${c.hot ? C.accentLine : C.lineStrong}`,
              fontFamily: F.mono, fontSize: 18, color: c.hot ? C.ink : C.inkMuted, whiteSpace: "nowrap",
              opacity: o, transform: `scale(${1 - converge * 0.5})`, boxShadow: "0 14px 36px -14px rgba(0,0,0,0.7)",
            }}
          >
            <span style={{ width: 8, height: 8, borderRadius: 2, background: c.hot ? C.accent : C.inkFaint }} />
            {c.name}
          </div>
        );
      })}

      {/* Count of real source files. */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 78, textAlign: "center", opacity: interpolate(frame, [2, 18], [0, 1], clamp) * (1 - converge) }}>
        <span style={{ display: "inline-flex", alignItems: "baseline", gap: 14, padding: "10px 22px", borderRadius: 999, border: `1px solid ${C.lineStrong}`, background: C.surface }}>
          <span style={{ fontFamily: F.mono, fontSize: 34, fontWeight: 500, color: C.accent, minWidth: 52, textAlign: "right" }}>{count}</span>
          <span style={{ fontFamily: F.mono, fontSize: 20, color: C.inkMuted }}>source files</span>
        </span>
      </div>

      {/* The line. */}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", opacity: headOut }}>
        <div style={{ fontFamily: F.sans, fontSize: 132, fontWeight: 600, letterSpacing: "-0.05em", lineHeight: 1.02, textAlign: "center", color: C.ink }}>
          <div>{l1.map((w, i) => <span key={w} style={word(26, i)}>{w}</span>)}</div>
          <div>
            {l2.slice(0, 2).map((w, i) => <span key={w} style={word(62, i)}>{w}</span>)}
            <span style={{ ...word(62, 2), marginRight: 0, fontFamily: F.serif, fontStyle: "italic", fontWeight: 400, letterSpacing: "-0.02em", fontSize: "1.06em", color: C.accent }}>don't.</span>
          </div>
        </div>
      </AbsoluteFill>

      {/* The turn: one command. */}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", opacity: oneIn, transform: `translateY(${(1 - oneIn) * 22}px)` }}>
        <div style={{ fontFamily: F.sans, fontSize: 132, fontWeight: 600, letterSpacing: "-0.05em", lineHeight: 1.02, color: C.ink }}>
          One <span style={{ fontFamily: F.serif, fontStyle: "italic", fontWeight: 400, letterSpacing: "-0.02em", fontSize: "1.06em", color: C.accent }}>command.</span>
        </div>
        <div style={{ marginTop: 52, opacity: cmdIn, transform: `translateY(${(1 - cmdIn) * 14}px)`, padding: "20px 34px", borderRadius: 14, background: C.surface, border: `1px solid ${C.lineStrong}`, fontFamily: F.mono, fontSize: 38, color: C.ink, minWidth: 470, boxShadow: "0 30px 70px -26px rgba(0,0,0,0.8)" }}>
          <span style={{ color: C.accent }}>$ </span>
          {typed}
          <span style={{ display: "inline-block", width: 17, height: 40, verticalAlign: "text-bottom", marginLeft: 2, background: caretOn ? C.accent : "transparent" }} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
