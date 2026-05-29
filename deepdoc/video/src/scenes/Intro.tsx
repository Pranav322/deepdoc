import {
  AbsoluteFill,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F } from "../constants";

const PARTICLE_COUNT = 48;

export const Intro = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const fadeIn  = interpolate(frame, [0, 22], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [90, 120], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const logoSpring     = spring({ frame, fps, config: { damping: 11, stiffness: 95, mass: 1.1 } });
  const tagSpring      = spring({ frame: Math.max(0, frame - 8),  fps, config: { damping: 16, stiffness: 130 } });
  const subtitleSpring = spring({ frame: Math.max(0, frame - 20), fps, config: { damping: 16, stiffness: 110 } });

  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden", opacity }}>

      {/* ── Animated aurora blobs ────────────────────────────── */}
      <div style={{
        position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none",
        WebkitMaskImage: "radial-gradient(ellipse 90% 80% at 50% 30%, black 20%, transparent 100%)",
        maskImage:        "radial-gradient(ellipse 90% 80% at 50% 30%, black 20%, transparent 100%)",
      }}>
        <div style={{
          position: "absolute", top: "-20%", left: "-8%", width: "65%", height: "100%",
          background: `radial-gradient(ellipse at 40% 40%, ${C.accentGlow} 0%, transparent 68%)`,
          filter: "blur(56px)",
          transform: `translate(${Math.sin(t * 0.7) * 50}px, ${Math.cos(t * 0.5) * 36}px)`,
        }} />
        <div style={{
          position: "absolute", top: "-10%", right: "-12%", width: "60%", height: "90%",
          background: `radial-gradient(ellipse at 60% 35%, rgba(55,120,255,0.14) 0%, transparent 65%)`,
          filter: "blur(64px)",
          transform: `translate(${Math.sin(t * 0.45 + 1) * 55}px, ${Math.cos(t * 0.65) * 38}px)`,
        }} />
        <div style={{
          position: "absolute", bottom: "0%", right: "15%", width: "38%", height: "55%",
          background: `radial-gradient(ellipse at 50% 60%, ${C.accentDim} 0%, transparent 65%)`,
          filter: "blur(52px)",
          transform: `translate(${Math.cos(t * 0.55) * 35}px, ${Math.sin(t * 0.38 + 2) * 24}px)`,
        }} />
      </div>

      {/* ── Particles ───────────────────────────────────────── */}
      {Array.from({ length: PARTICLE_COUNT }, (_, i) => {
        const px   = random(`px-${i}`) * 1920;
        const py   = random(`py-${i}`) * 1080;
        const size = random(`ps-${i}`) * 2.5 + 1;
        const spd  = random(`psp-${i}`) * 0.25 + 0.08;
        const del  = random(`pd-${i}`) * 35;
        const pOpacity = random(`po-${i}`) * 0.35 + 0.1;
        const po = interpolate(frame, [del, del + 18], [0, pOpacity], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        });
        return (
          <div key={i} style={{
            position: "absolute",
            left: px,
            top: ((py - frame * spd * 0.6) % 1080 + 1080) % 1080,
            width: size, height: size,
            borderRadius: "50%",
            background: i % 3 === 0 ? C.accent : i % 3 === 1 ? C.blue : "#fff",
            opacity: po,
            boxShadow: i % 5 === 0 ? `0 0 6px ${C.accent}` : "none",
          }} />
        );
      })}

      {/* ── Dot grid ─────────────────────────────────────────── */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        backgroundImage: `radial-gradient(circle, rgba(255,255,255,0.10) 1px, transparent 1px)`,
        backgroundSize: "36px 36px",
        WebkitMaskImage: "radial-gradient(ellipse 70% 65% at 50% 40%, black 30%, transparent 100%)",
        maskImage:        "radial-gradient(ellipse 70% 65% at 50% 40%, black 30%, transparent 100%)",
        opacity: 0.7,
      }} />

      {/* ── Content ──────────────────────────────────────────── */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
      }}>
        {/* Badge */}
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          border: `1px solid ${C.lineStrong}`,
          background: `${C.surface}dd`,
          borderRadius: 100, padding: "8px 20px", marginBottom: 40,
          fontFamily: F.mono, fontSize: 15, color: C.inkMuted, letterSpacing: "0.02em",
          opacity: tagSpring, transform: `translateY(${(1 - tagSpring) * 20}px)`,
        }}>
          <span style={{
            width: 8, height: 8, borderRadius: "50%",
            background: C.accent, boxShadow: `0 0 14px ${C.accent}`,
            display: "inline-block",
          }} />
          v2.3 · MDX-safe generation · One-key chatbot
        </div>

        {/* Logo */}
        <h1 style={{
          fontFamily: F.sans, fontSize: 144, fontWeight: 800,
          letterSpacing: "-0.05em", lineHeight: 1,
          margin: 0, textAlign: "center",
          background: `linear-gradient(140deg, #ffffff 15%, ${C.accent} 100%)`,
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          opacity: logoSpring,
          transform: `translateY(${(1 - logoSpring) * 64}px) scale(${0.88 + logoSpring * 0.12})`,
        }}>
          DeepDoc
        </h1>

        {/* Tagline */}
        <p style={{
          fontFamily: F.sans, fontSize: 30, fontWeight: 400,
          color: C.inkMuted, textAlign: "center",
          margin: "26px 0 0", maxWidth: 820, lineHeight: 1.45,
          opacity: subtitleSpring * fadeIn,
          transform: `translateY(${(1 - subtitleSpring) * 28}px)`,
        }}>
          Engineering docs your team will{" "}
          <span style={{ color: C.ink, fontWeight: 600 }}>actually read.</span>
        </p>
      </div>
    </AbsoluteFill>
  );
};
