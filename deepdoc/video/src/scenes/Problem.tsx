import {
  AbsoluteFill,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F, SPRING } from "../constants";

const FILES = [
  "auth/middleware.py",   "api/routes.ts",        "db/models.py",
  "services/billing.ts",  "utils/crypto.py",       "workers/queue.py",
  "lib/cache.ts",         "core/config.py",        "api/users.ts",
  "services/email.py",    "lib/tokens.ts",         "core/events.py",
];

export const Problem = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [78, 105], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const line1Spring = spring({ frame, fps, config: SPRING.snappy });
  const line2Spring = spring({ frame: Math.max(0, frame - 26), fps, config: SPRING.snappy });

  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden", opacity }}>

      {/* Scattered file pills — calm background texture, upright and sparse
          (previously randomly rotated + tightly packed, which read as
          visual noise rather than a considered detail) */}
      {FILES.map((name, i) => {
        const cx = random(`cx-${i}`) * 1500 + 210;
        const cy = random(`cy-${i}`) * 820  + 90;
        const del = random(`cd-${i}`) * 24;
        const fo = interpolate(frame, [del, del + 16], [0, 1], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        });
        const drift = frame * (random(`cspd-${i}`) * 0.1 + 0.03);
        return (
          <div key={i} style={{
            position: "absolute",
            left: cx,
            top: cy - drift,
            opacity: fo * 0.22,
            border: `1px solid ${C.lineStrong}`,
            background: C.surface,
            borderRadius: 8,
            padding: "7px 15px",
            fontFamily: F.mono,
            fontSize: 13,
            color: C.inkMuted,
            whiteSpace: "nowrap",
          }}>
            {name}
          </div>
        );
      })}

      {/* Central message */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        background: `radial-gradient(ellipse 58% 52% at 50% 50%, ${C.bg}f0 45%, transparent 100%)`,
      }}>
        <p style={{
          fontFamily: F.sans, fontSize: 66, fontWeight: 700,
          color: C.inkMuted, margin: "0 0 8px",
          letterSpacing: "-0.03em", textAlign: "center",
          opacity: line1Spring,
          transform: `translateY(${(1 - line1Spring) * 32}px)`,
        }}>
          Your codebase grows.
        </p>

        <p style={{
          fontFamily: F.sans, fontSize: 66, fontWeight: 800,
          color: C.ink, margin: "0 0 48px",
          letterSpacing: "-0.03em", textAlign: "center",
          opacity: line2Spring,
          transform: `translateY(${(1 - line2Spring) * 32}px)`,
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
          fontFamily: F.sans, fontSize: 21, color: C.inkFaint,
          margin: 0, lineHeight: 1.7, textAlign: "center",
          opacity: interpolate(frame, [50, 70], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          transform: `translateY(${interpolate(frame, [50, 70], [16, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px)`,
        }}>
          New teammates onboard from Slack threads.
          <br />
          Endpoints get reverse-engineered. Architecture lives in someone's head.
        </p>
      </div>
    </AbsoluteFill>
  );
};
