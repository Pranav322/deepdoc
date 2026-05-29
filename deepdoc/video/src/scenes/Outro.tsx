import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F } from "../constants";

const TAGS = ["Python 3.10+", "Node 18+", "MIT License", "deepdoc.dev"];

export const Outro = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 22], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [108, 135], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const titleSpring = spring({ frame, fps, config: { damping: 12, stiffness: 100, mass: 1.0 } });
  const cmdSpring   = spring({ frame: Math.max(0, frame - 16), fps, config: { damping: 15, stiffness: 115 } });
  const tagsSpring  = spring({ frame: Math.max(0, frame - 30), fps, config: { damping: 16, stiffness: 120 } });

  // Pulse on the accent dot
  const pulse = 0.8 + Math.sin(frame * 0.18) * 0.2;

  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden", opacity }}>

      {/* Aurora */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        WebkitMaskImage: "radial-gradient(ellipse 80% 70% at 50% 50%, black 30%, transparent 100%)",
        maskImage:        "radial-gradient(ellipse 80% 70% at 50% 50%, black 30%, transparent 100%)",
      }}>
        <div style={{
          position: "absolute", top: "-30%", left: "-10%",
          width: "70%", height: "110%",
          background: `radial-gradient(ellipse at 40% 40%, ${C.accentGlow} 0%, transparent 65%)`,
          filter: "blur(64px)",
        }} />
        <div style={{
          position: "absolute", bottom: "-20%", right: "-5%",
          width: "55%", height: "90%",
          background: `radial-gradient(ellipse at 60% 60%, rgba(55,120,255,0.14) 0%, transparent 65%)`,
          filter: "blur(72px)",
        }} />
      </div>

      {/* Dot grid */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        backgroundImage: `radial-gradient(circle, rgba(255,255,255,0.10) 1px, transparent 1px)`,
        backgroundSize: "36px 36px",
        WebkitMaskImage: "radial-gradient(ellipse 70% 65% at 50% 50%, black 30%, transparent 100%)",
        maskImage:        "radial-gradient(ellipse 70% 65% at 50% 50%, black 30%, transparent 100%)",
        opacity: 0.65,
      }} />

      {/* Content */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
      }}>
        {/* Pulsing accent dot */}
        <div style={{
          width: 14, height: 14, borderRadius: "50%",
          background: C.accent,
          boxShadow: `0 0 ${20 * pulse}px ${C.accent}, 0 0 ${40 * pulse}px ${C.accentGlow}`,
          marginBottom: 36,
          opacity: titleSpring,
          transform: `scale(${0.8 + titleSpring * 0.2})`,
        }} />

        {/* Domain */}
        <h2 style={{
          fontFamily: F.sans, fontSize: 100, fontWeight: 800,
          letterSpacing: "-0.045em", margin: "0 0 16px", textAlign: "center",
          background: `linear-gradient(140deg, #ffffff 20%, ${C.accent} 100%)`,
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          opacity: titleSpring,
          transform: `translateY(${(1 - titleSpring) * 48}px)`,
        }}>
          deepdoc.dev
        </h2>

        {/* Install command */}
        <div style={{
          fontFamily: F.mono, fontSize: 24, color: C.accent,
          marginBottom: 52, letterSpacing: "0.01em",
          padding: "12px 28px",
          border: `1px solid ${C.accent}40`,
          background: `${C.surface}cc`,
          borderRadius: 12,
          boxShadow: `0 0 40px ${C.accentDim}`,
          opacity: cmdSpring,
          transform: `translateY(${(1 - cmdSpring) * 22}px)`,
        }}>
          pip install deepdoc
        </div>

        {/* Tags */}
        <div style={{
          display: "flex", gap: 12,
          opacity: tagsSpring,
          transform: `translateY(${(1 - tagsSpring) * 18}px)`,
        }}>
          {TAGS.map((tag) => (
            <span key={tag} style={{
              border: `1px solid ${C.lineStrong}`,
              borderRadius: 100, padding: "8px 22px",
              fontFamily: F.sans, fontSize: 15, color: C.inkMuted,
              background: C.surface,
            }}>
              {tag}
            </span>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
