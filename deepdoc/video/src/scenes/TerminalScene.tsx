import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F, SPRING } from "../constants";
import { GENERATION_LOG, GENERATION_QUEUED, GENERATION_TOTAL_PAGES } from "../data";

const COMMAND = "$ deepdoc generate";
const ROW_START = 50;
const ROW_GAP = 32;
// Progress bar must finish ramping before the scene's own fade-out begins
// (see fadeOut window below) or it visibly snaps mid-animation.
const PROGRESS_START = ROW_START + GENERATION_LOG.length * ROW_GAP + 8;
const PROGRESS_RAMP = 20;

// Real output from `deepdoc generate` — the exact page titles, word counts,
// warning badges and timings the CLI actually prints.
export const TerminalScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [176, 195], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const windowSpring = spring({ frame, fps, config: SPRING.soft });

  const charsToShow = Math.floor(
    interpolate(frame, [16, 40], [0, COMMAND.length], {
      extrapolateLeft: "clamp", extrapolateRight: "clamp",
    })
  );
  const displayCommand = COMMAND.slice(0, charsToShow);
  const cursorVisible  = frame < 44 || Math.floor(frame / 15) % 2 === 0;

  const queuedProgress = interpolate(frame, [PROGRESS_START, PROGRESS_START + PROGRESS_RAMP], [0, 16], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ background: C.bg, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity }}>

      {/* Label */}
      <div style={{
        fontFamily: F.mono, fontSize: 14, color: C.inkFaint,
        letterSpacing: "0.18em", textTransform: "uppercase",
        marginBottom: 34, opacity: fadeIn,
      }}>
        Phase 3 / 5 · Generating {GENERATION_TOTAL_PAGES} pages
      </div>

      {/* Terminal window — near full-bleed instead of a small 980px box
          floating in a sea of black */}
      <div style={{
        width: "100%", maxWidth: 1740, borderRadius: 20,
        border: `1px solid ${C.lineStrong}`,
        background: C.surface, overflow: "hidden",
        transform: `translateY(${(1 - windowSpring) * 44}px) scale(${0.94 + windowSpring * 0.06})`,
        boxShadow: "0 48px 100px rgba(0,0,0,0.7)",
      }}>
        {/* Title bar */}
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          borderBottom: `1px solid ${C.line}`,
          padding: "16px 22px",
        }}>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ width: 13, height: 13, borderRadius: "50%", background: "rgba(255,95,86,0.75)" }} />
            <span style={{ width: 13, height: 13, borderRadius: "50%", background: "rgba(255,189,46,0.75)" }} />
            <span style={{ width: 13, height: 13, borderRadius: "50%", background: "rgba(39,201,63,0.75)" }} />
          </div>
          <span style={{ margin: "0 auto", fontFamily: F.mono, fontSize: 14, color: C.inkFaint }}>
            zsh — deepdoc
          </span>
        </div>

        {/* Body */}
        <div style={{ padding: "36px 44px 42px", fontFamily: F.mono, fontSize: 21, color: C.ink, minHeight: 470 }}>
          <div style={{ marginBottom: 26 }}>
            {displayCommand}
            {cursorVisible && (
              <span style={{
                display: "inline-block", width: 12, height: 24,
                background: C.accent, marginLeft: 2, verticalAlign: "middle", opacity: 0.9,
              }} />
            )}
          </div>

          {GENERATION_LOG.map((row, i) => {
            const start = ROW_START + i * ROW_GAP;
            const lo = interpolate(frame, [start, start + 10], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            const shift = interpolate(frame, [start, start + 10], [8, 0], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            return (
              <div key={row.title} style={{
                display: "flex", alignItems: "baseline", gap: 16,
                opacity: lo, transform: `translateY(${shift}px)`,
                padding: "12px 0",
              }}>
                <span style={{ color: C.accent }}>✓</span>
                <span style={{ color: C.ink, fontWeight: 600 }}>{row.title}</span>
                <span style={{ color: C.inkFaint, fontSize: 17 }}>({row.meta})</span>
                <span style={{ marginLeft: "auto", color: C.inkMuted, fontSize: 17 }}>{row.time}</span>
                {row.warnings ? (
                  <span style={{ color: C.orange, fontSize: 17 }}>⚠ {row.warnings}</span>
                ) : null}
              </div>
            );
          })}

          {/* Queued page with live progress bar */}
          <div style={{
            display: "flex", alignItems: "center", gap: 16, padding: "18px 0 0",
            opacity: interpolate(frame, [PROGRESS_START - 10, PROGRESS_START], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            }),
          }}>
            <span style={{ color: C.inkFaint }}>…</span>
            <span style={{ color: C.inkMuted }}>Queuing {GENERATION_QUEUED}</span>
            <div style={{ flex: 1, height: 9, borderRadius: 4, background: C.surfaceRaised, overflow: "hidden" }}>
              <div style={{
                height: "100%", borderRadius: 4, width: `${queuedProgress}%`,
                background: `linear-gradient(90deg, ${C.teal}, ${C.accent})`,
              }} />
            </div>
            <span style={{ color: C.inkMuted, fontSize: 17, width: 44, textAlign: "right" }}>
              {Math.round(queuedProgress)}%
            </span>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
