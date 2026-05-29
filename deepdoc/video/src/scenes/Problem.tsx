import {
  AbsoluteFill,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F } from "../constants";

const FILES = [
  "auth/middleware.py",   "api/routes.ts",        "db/models.py",
  "services/billing.ts",  "utils/crypto.py",       "api/webhooks.ts",
  "workers/queue.py",     "lib/cache.ts",          "core/config.py",
  "api/users.ts",         "db/migrations/*.sql",   "services/email.py",
  "lib/tokens.ts",        "scripts/seed.py",       "api/payments.ts",
  "utils/logger.py",      "services/storage.ts",   "core/events.py",
];

export const Problem = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [78, 105], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const line1Spring = spring({ frame, fps, config: { damping: 16, stiffness: 130 } });
  const line2Spring = spring({ frame: Math.max(0, frame - 30), fps, config: { damping: 16, stiffness: 130 } });

  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden", opacity }}>

      {/* ── Scattered file pills (background chaos) ──────────── */}
      {FILES.map((name, i) => {
        const cx = random(`cx-${i}`) * 1600 + 160;
        const cy = random(`cy-${i}`) * 900  + 90;
        const rot = (random(`cr-${i}`) - 0.5) * 24;
        const del = random(`cd-${i}`) * 28;
        const fo = interpolate(frame, [del, del + 14], [0, 1], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        });
        const scale = interpolate(frame, [del, del + 14], [0.6, 1], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        });
        // Gently drift upward
        const drift = frame * (random(`cspd-${i}`) * 0.18 + 0.06);
        return (
          <div key={i} style={{
            position: "absolute",
            left: cx,
            top: cy - drift,
            opacity: fo * 0.28,
            transform: `rotate(${rot}deg) scale(${scale})`,
            border: `1px solid ${C.lineStrong}`,
            background: C.surface,
            borderRadius: 8,
            padding: "6px 14px",
            fontFamily: F.mono,
            fontSize: 13,
            color: C.inkMuted,
            whiteSpace: "nowrap",
          }}>
            {name}
          </div>
        );
      })}

      {/* ── Central message ──────────────────────────────────── */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        // Frosted overlay to make text pop over the file pills
        background: `radial-gradient(ellipse 60% 55% at 50% 50%, ${C.bg}e8 40%, transparent 100%)`,
      }}>
        <p style={{
          fontFamily: F.sans, fontSize: 68, fontWeight: 700,
          color: C.inkMuted, margin: "0 0 10px",
          letterSpacing: "-0.03em", textAlign: "center",
          opacity: line1Spring,
          transform: `translateY(${(1 - line1Spring) * 36}px)`,
        }}>
          Your codebase grows.
        </p>

        <p style={{
          fontFamily: F.sans, fontSize: 68, fontWeight: 800,
          color: C.ink, margin: "0 0 52px",
          letterSpacing: "-0.03em", textAlign: "center",
          opacity: line2Spring,
          transform: `translateY(${(1 - line2Spring) * 36}px)`,
        }}>
          The docs{" "}
          <span style={{
            background: `linear-gradient(135deg, #FF5F87, #FF9E00)`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          }}>
            don't.
          </span>
        </p>

        <p style={{
          fontFamily: F.sans, fontSize: 22, color: C.inkFaint,
          margin: 0, lineHeight: 1.65, textAlign: "center",
          opacity: interpolate(frame, [52, 72], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          transform: `translateY(${interpolate(frame, [52, 72], [18, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px)`,
        }}>
          New teammates onboard from Slack threads.
          <br />
          Endpoints get reverse-engineered. Architecture lives in someone's head.
        </p>
      </div>
    </AbsoluteFill>
  );
};
