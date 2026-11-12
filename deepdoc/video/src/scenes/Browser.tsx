import { AbsoluteFill, Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Caption, type Cue } from "../components/Caption";
import { Window } from "../components/Window";
import { C, F, SPRING, T } from "../constants";

// Real pages, captured from the live site DeepDoc generated for this repo
// (scripts/capture-site.mjs). The captures are 1600 CSS px wide; the sidebar
// and table of contents are fixed on the real site, so only the middle
// column scrolls here.
const PAGE_W = 1600, VIEW_H = 900, SIDEBAR = 290, TOC_X = 1248;
const S = 0.94; // capture to window scale
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const ease = Easing.inOut(Easing.cubic);

const Page = ({ src, scroll }: { src: string; scroll: number }) => {
  const img = (offsetX: number, y: number) => (
    <Img src={staticFile(src)} style={{ position: "absolute", left: -offsetX * S, top: -y * S, width: PAGE_W * S, maxWidth: "none" }} />
  );
  const col = (x: number, w: number, y: number) => (
    <div style={{ position: "absolute", left: x * S, top: 0, width: w * S, height: VIEW_H * S, overflow: "hidden" }}>{img(x, y)}</div>
  );
  return (
    <>
      {col(SIDEBAR, TOC_X - SIDEBAR, scroll)}
      {col(TOC_X, PAGE_W - TOC_X, 0)}
      {col(0, SIDEBAR, 0)}
    </>
  );
};

const CLICK = 300;

const cues: Cue[] = [
  { from: 14, to: 112, title: "The site it wrote", note: "cloud.deepdoc.tech/pranav322/youtube-notes" },
  { from: 116, to: 292, title: "Every page cites its sources", note: "then explains the architecture" },
  { from: CLICK + 8, to: T.BROWSER - T.OVERLAP, title: "One page per concept", note: "19 pages, grouped by domain" },
];

export const Browser = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const inP = spring({ frame, fps, config: SPRING.soft });
  const exit = interpolate(frame, [T.BROWSER - T.OVERLAP, T.BROWSER], [0, 1], { ...clamp, easing: ease });

  // Page one: rest on the source list, then scroll to the architecture diagram.
  const scrollA = interpolate(frame, [112, 215], [0, 930], { ...clamp, easing: ease });
  // Page two, after the click. The view also pushes in on the article, the way
  // you lean in to read, which takes the table of contents out of frame.
  const zoom = interpolate(frame, [CLICK, CLICK + 16], [1, 1.3], { ...clamp, easing: ease });
  const swap = interpolate(frame, [CLICK + 6, CLICK + 18], [0, 1], clamp);
  const scrollB = interpolate(frame, [CLICK + 56, CLICK + 146], [0, 520], { ...clamp, easing: ease });

  // The source-files callout.
  const box = interpolate(frame, [38, 56], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) }) * interpolate(frame, [100, 112], [1, 0], clamp);

  // Pointer: drifts in, moves to the sidebar link, clicks.
  const move = interpolate(frame, [240, 290], [0, 1], { ...clamp, easing: ease });
  const cx = interpolate(move, [0, 1], [1040, 140]) * S;
  const cy = interpolate(move, [0, 1], [420, 609]) * S;
  const cursorO = interpolate(frame, [228, 240], [0, 1], clamp) * interpolate(frame, [CLICK + 4, CLICK + 14], [1, 0], clamp);
  const press = interpolate(frame, [CLICK - 3, CLICK, CLICK + 5], [1, 0.86, 1], clamp);
  const ripple = interpolate(frame, [CLICK, CLICK + 16], [0, 1], clamp);
  const linkHot = interpolate(frame, [CLICK - 12, CLICK - 2], [0, 1], clamp) * (1 - swap);

  const W = PAGE_W * S, H = VIEW_H * S + 50;

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: Math.min(1, inP * 1.4) * (1 - exit), transform: `translateY(${(1 - inP) * 140 - 22 - exit * 30}px) scale(${0.95 + inP * 0.05 - exit * 0.05})` }}>
        <Window light title="cloud.deepdoc.tech/pranav322/youtube-notes" width={W} height={H}>
          <div style={{ position: "absolute", inset: 0, transform: `scale(${zoom})`, transformOrigin: "0 0" }}>
            <div style={{ position: "absolute", inset: 0, opacity: 1 - swap }}><Page src="site/overview-light.jpg" scroll={scrollA} /></div>
            <div style={{ position: "absolute", inset: 0, opacity: swap }}><Page src="site/api-light.jpg" scroll={scrollB} /></div>
          </div>

          {/* Callout: the files this page was written from. */}
          <div style={{ position: "absolute", left: 372 * S, top: 112 * S, width: 470 * S, height: 420 * S, borderRadius: 12, border: `2px solid ${C.accent}`, boxShadow: `0 0 0 6px ${C.accentDim}`, opacity: box, transform: `scale(${0.97 + box * 0.03})` }} />
          <div style={{ position: "absolute", left: 866 * S, top: 290 * S, opacity: box, transform: `translateX(${(1 - box) * -14}px)`, display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 44, height: 2, background: C.accent }} />
            <div style={{ padding: "10px 16px", borderRadius: 10, background: C.bg, color: C.ink, fontFamily: F.sans, fontSize: 21, fontWeight: 600, letterSpacing: "-0.015em", boxShadow: "0 12px 30px -10px rgba(0,0,0,0.5)" }}>
              Written from these files
            </div>
          </div>

          {/* The sidebar link being clicked. */}
          <div style={{ position: "absolute", left: 30 * S, top: 592 * S, width: 232 * S, height: 34 * S, borderRadius: 8, background: "rgba(235,62,37,0.12)", opacity: linkHot }} />
          <div style={{ position: "absolute", left: cx - 22, top: cy - 22, width: 44, height: 44, borderRadius: 22, border: `2px solid ${C.accent}`, opacity: (1 - ripple) * (frame >= CLICK ? 1 : 0), transform: `scale(${0.4 + ripple * 1.3})` }} />
          <svg width="30" height="30" viewBox="0 0 24 24" style={{ position: "absolute", left: cx, top: cy, opacity: cursorO, transform: `scale(${press})`, transformOrigin: "0 0", filter: "drop-shadow(0 3px 6px rgba(0,0,0,0.35))" }}>
            <path d="M5 3l14 8.2-6.3 1.4 3.4 7-2.6 1.2-3.4-7L5 18z" fill="#111110" stroke="#FFFFFF" strokeWidth="1.4" strokeLinejoin="round" />
          </svg>
        </Window>
      </AbsoluteFill>
      <div style={{ opacity: 1 - exit }}><Caption cues={cues} /></div>
    </AbsoluteFill>
  );
};
