import {
  AbsoluteFill,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F, SPRING } from "../constants";

const PARTICLE_COUNT = 26;

export const Intro = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const fadeIn  = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [80, 105], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const logoSpring     = spring({ frame, fps, config: SPRING.soft });
  const tagSpring      = spring({ frame: Math.max(0, frame - 6),  fps, config: SPRING.snappy });
  const subtitleSpring = spring({ frame: Math.max(0, frame - 18), fps, config: SPRING.snappy });

  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden", opacity }}>

      {/* ── Aurora, full-bleed and generously blurred so it never reads
          as a hard-edged rectangle (the old CSS-mask approach clipped
          visibly at the panel edge) ─────────────────────────────── */}
      <div style={{ position: "absolute", inset: -200, overflow: "hidden", pointerEvents: "none" }}>
        <div style={{
          position: "absolute", top: "-10%", left: "6%", width: "56%", height: "78%",
          background: `radial-gradient(ellipse at 40% 40%, ${C.accentGlow} 0%, transparent 70%)`,
          filter: "blur(120px)",
          transform: `translate(${Math.sin(t * 0.6) * 36}px, ${Math.cos(t * 0.42) * 26}px)`,
        }} />
        <div style={{
          position: "absolute", top: "-4%", right: "8%", width: "50%", height: "70%",
          background: `radial-gradient(ellipse at 60% 35%, rgba(0,229,160,0.16) 0%, transparent 68%)`,
          filter: "blur(130px)",
          transform: `translate(${Math.sin(t * 0.4 + 1) * 30}px, ${Math.cos(t * 0.55) * 24}px)`,
        }} />
      </div>

      {/* Vignette — feathers the aurora naturally instead of a mask edge */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: `radial-gradient(ellipse 64% 58% at 50% 42%, transparent 0%, ${C.bg} 90%)`,
      }} />

      {/* Dot grid */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        backgroundImage: `radial-gradient(circle, rgba(255,255,255,0.08) 1px, transparent 1px)`,
        backgroundSize: "40px 40px",
        opacity: 0.5,
      }} />
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: `radial-gradient(ellipse 58% 55% at 50% 42%, transparent 12%, ${C.bg} 86%)`,
      }} />

      {/* Particles — sparse, calm drift */}
      {Array.from({ length: PARTICLE_COUNT }, (_, i) => {
        const px   = random(`px-${i}`) * 1920;
        const py   = random(`py-${i}`) * 1080;
        const size = random(`ps-${i}`) * 2 + 1;
        const spd  = random(`psp-${i}`) * 0.16 + 0.05;
        const del  = random(`pd-${i}`) * 30;
        const pOpacity = random(`po-${i}`) * 0.26 + 0.08;
        const po = interpolate(frame, [del, del + 20], [0, pOpacity], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        });
        return (
          <div key={i} style={{
            position: "absolute",
            left: px,
            top: ((py - frame * spd * 0.6) % 1080 + 1080) % 1080,
            width: size, height: size,
            borderRadius: "50%",
            background: i % 3 === 0 ? C.accent : "#fff",
            opacity: po,
          }} />
        );
      })}

      {/* Content */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
      }}>
        {/* Badge */}
        <div style={{
          display: "flex", alignItems: "center", gap: 9,
          border: `1px solid ${C.lineStrong}`,
          background: `${C.surface}dd`,
          borderRadius: 100, padding: "9px 22px", marginBottom: 36,
          fontFamily: F.mono, fontSize: 14, color: C.inkMuted, letterSpacing: "0.02em",
          opacity: tagSpring, transform: `translateY(${(1 - tagSpring) * 16}px)`,
        }}>
          <span style={{
            width: 7, height: 7, borderRadius: "50%",
            background: C.accent, boxShadow: `0 0 12px ${C.accent}`,
            display: "inline-block",
          }} />
          Docs that regenerate themselves, grounded in your code
        </div>

        {/* Logo */}
        <h1 style={{
          fontFamily: F.sans, fontSize: 148, fontWeight: 800,
          letterSpacing: "-0.045em", lineHeight: 1,
          margin: 0, textAlign: "center",
          background: `linear-gradient(140deg, #ffffff 15%, ${C.accent} 100%)`,
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          opacity: logoSpring,
          transform: `translateY(${(1 - logoSpring) * 50}px) scale(${0.92 + logoSpring * 0.08})`,
        }}>
          DeepDoc
        </h1>

        {/* Tagline */}
        <p style={{
          fontFamily: F.sans, fontSize: 28, fontWeight: 400,
          color: C.inkMuted, textAlign: "center",
          margin: "24px 0 0", maxWidth: 760, lineHeight: 1.5,
          opacity: subtitleSpring * fadeIn,
          transform: `translateY(${(1 - subtitleSpring) * 20}px)`,
        }}>
          Engineering docs your team will{" "}
          <span style={{ color: C.ink, fontWeight: 600 }}>actually read.</span>
        </p>
      </div>
    </AbsoluteFill>
  );
};
