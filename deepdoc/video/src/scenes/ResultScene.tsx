import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, F } from "../constants";

const NAV_ITEMS = [
  { label: "Start Here",           indent: 0 },
  { label: "Architecture Overview",indent: 0 },
  { label: "Auth & Middleware",     indent: 1 },
  { label: "API Endpoints",         indent: 0 },
  { label: "  POST /payments",      indent: 1 },
  { label: "  POST /webhooks",      indent: 1 },
  { label: "Billing & Usage",       indent: 0 },
  { label: "Background Jobs",       indent: 0 },
  { label: "AI Chat Experience",    indent: 0 },
];

const CHAT: Array<{ role: "user" | "bot"; text: string; ref?: string }> = [
  { role: "user", text: "Where does billing verification happen?" },
  {
    role: "bot",
    text: "Payment verification runs in the Razorpay billing flow, then persisted through usage and project records.",
    ref: "billing/routes.py:41-88",
  },
  { role: "user", text: "What's the chatbot index built from?" },
  {
    role: "bot",
    text: "Source archives: FAISS vector + SQLite FTS over all MDX pages and symbol chunks.",
    ref: "chatbot/indexer.py:12-44",
  },
];

export const ResultScene = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn  = interpolate(frame, [0, 24], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [152, 180], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const headingSpring = spring({ frame, fps, config: { damping: 14, stiffness: 115 } });
  const leftSpring    = spring({ frame: Math.max(0, frame - 10), fps, config: { damping: 13, stiffness: 100 } });
  const rightSpring   = spring({ frame: Math.max(0, frame - 20), fps, config: { damping: 13, stiffness: 100 } });

  return (
    <AbsoluteFill style={{
      background: C.bg, opacity,
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
      padding: "0 72px",
    }}>

      {/* Ambient glow */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: `radial-gradient(ellipse 60% 50% at 50% 50%, ${C.accentDim} 0%, transparent 70%)`,
        opacity: 0.5,
      }} />

      {/* Header */}
      <div style={{ marginBottom: 44, textAlign: "center" }}>
        <div style={{
          fontFamily: F.mono, fontSize: 13, color: C.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
          marginBottom: 14, opacity: fadeIn,
        }}>
          What you get
        </div>
        <h2 style={{
          fontFamily: F.sans, fontSize: 52, fontWeight: 800,
          color: C.ink, margin: 0, textAlign: "center", letterSpacing: "-0.035em",
          opacity: headingSpring,
          transform: `translateY(${(1 - headingSpring) * 28}px)`,
        }}>
          A site. A chatbot.{" "}
          <span style={{
            background: `linear-gradient(135deg, ${C.accent}, ${C.teal})`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
          }}>
            Grounded in your source.
          </span>
        </h2>
      </div>

      <div style={{ display: "flex", gap: 20, width: "100%", maxWidth: 1500 }}>

        {/* ── Docs browser mock ────────────────────────────── */}
        <div style={{
          flex: 1.1,
          border: `1px solid ${C.lineStrong}`,
          borderRadius: 18, background: C.surface, overflow: "hidden",
          transform: `translateX(${(1 - leftSpring) * -60}px)`,
          opacity: leftSpring,
          boxShadow: `0 0 80px rgba(55,120,255,0.10)`,
        }}>
          {/* Browser chrome */}
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            borderBottom: `1px solid ${C.line}`,
            padding: "11px 16px", background: C.surfaceRaised,
          }}>
            <div style={{ display: "flex", gap: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: "rgba(255,95,86,0.65)" }} />
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: "rgba(255,189,46,0.65)" }} />
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: "rgba(39,201,63,0.65)" }} />
            </div>
            <div style={{
              flex: 1, marginLeft: 10, background: C.surface,
              borderRadius: 6, padding: "4px 12px",
              fontFamily: F.mono, fontSize: 11, color: C.inkFaint,
              border: `1px solid ${C.line}`,
            }}>
              localhost:3000/docs
            </div>
          </div>

          {/* Docs layout */}
          <div style={{ display: "flex", height: 320 }}>
            {/* Sidebar */}
            <div style={{
              width: 210, borderRight: `1px solid ${C.line}`,
              padding: "16px 0", overflowY: "hidden",
            }}>
              <div style={{
                fontFamily: F.mono, fontSize: 10, color: C.inkFaint,
                letterSpacing: "0.12em", textTransform: "uppercase",
                padding: "0 16px 12px",
              }}>
                Documentation
              </div>
              {NAV_ITEMS.map((item, i) => {
                const itemOpacity = interpolate(frame, [28 + i * 8, 28 + i * 8 + 12], [0, 1], {
                  extrapolateLeft: "clamp", extrapolateRight: "clamp",
                });
                const isFirst = i === 0;
                return (
                  <div key={i} style={{
                    padding: `5px ${16 + item.indent * 12}px`,
                    fontFamily: F.sans, fontSize: 12,
                    color: isFirst ? C.accent : C.inkMuted,
                    background: isFirst ? `${C.accent}10` : "transparent",
                    borderLeft: isFirst ? `2px solid ${C.accent}` : "2px solid transparent",
                    opacity: itemOpacity,
                    whiteSpace: "nowrap", overflow: "hidden",
                  }}>
                    {item.label}
                  </div>
                );
              })}
            </div>

            {/* Main content */}
            <div style={{ flex: 1, padding: "22px 24px", overflow: "hidden" }}>
              {/* Page title */}
              <div style={{
                fontFamily: F.sans, fontSize: 22, fontWeight: 700,
                color: C.ink, marginBottom: 12,
                opacity: interpolate(frame, [32, 48], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
              }}>
                Architecture Overview
              </div>
              {/* Fake content lines */}
              {[100, 85, 92, 70, 88, 76, 60].map((w, i) => {
                const lo = interpolate(frame, [40 + i * 6, 52 + i * 6], [0, 1], {
                  extrapolateLeft: "clamp", extrapolateRight: "clamp",
                });
                return (
                  <div key={i} style={{
                    height: 9, borderRadius: 4, marginBottom: 8,
                    width: `${w}%`,
                    background: i === 0
                      ? `linear-gradient(90deg, ${C.ink}30, ${C.ink}10)`
                      : `linear-gradient(90deg, ${C.inkFaint}40, ${C.inkFaint}15)`,
                    opacity: lo,
                  }} />
                );
              })}
              {/* Callout box */}
              <div style={{
                marginTop: 14, padding: "10px 14px",
                border: `1px solid ${C.accent}40`,
                borderLeft: `3px solid ${C.accent}`,
                borderRadius: 6, background: `${C.accent}08`,
                opacity: interpolate(frame, [80, 96], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
              }}>
                <div style={{
                  fontFamily: F.mono, fontSize: 11, color: C.accent, marginBottom: 4,
                }}>
                  Source-grounded
                </div>
                <div style={{
                  fontFamily: F.sans, fontSize: 11, color: C.inkMuted, lineHeight: 1.5,
                }}>
                  Every claim maps back to a file path + line range in your repo.
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Chatbot mock ─────────────────────────────────── */}
        <div style={{
          flex: 0.9,
          border: `1px solid rgba(155,127,255,0.35)`,
          borderRadius: 18, background: C.surface, overflow: "hidden",
          transform: `translateX(${(1 - rightSpring) * 60}px)`,
          opacity: rightSpring,
          boxShadow: `0 0 80px rgba(155,127,255,0.10)`,
        }}>
          {/* Chat header */}
          <div style={{
            display: "flex", alignItems: "center", gap: 10,
            borderBottom: `1px solid ${C.line}`,
            padding: "14px 18px", background: C.surfaceRaised,
          }}>
            <div style={{
              width: 8, height: 8, borderRadius: "50%",
              background: C.purple, boxShadow: `0 0 10px ${C.purple}`,
            }} />
            <span style={{
              fontFamily: F.sans, fontSize: 14, fontWeight: 600, color: C.ink,
            }}>
              DeepDoc Chatbot
            </span>
            <span style={{
              marginLeft: "auto", fontFamily: F.mono, fontSize: 11,
              color: C.inkFaint,
            }}>
              1,247 chunks indexed
            </span>
          </div>

          {/* Chat messages */}
          <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12, height: 290, overflow: "hidden" }}>
            {CHAT.map((msg, i) => {
              const msgOpacity = interpolate(frame, [36 + i * 22, 48 + i * 22], [0, 1], {
                extrapolateLeft: "clamp", extrapolateRight: "clamp",
              });
              const msgShift = interpolate(frame, [36 + i * 22, 48 + i * 22], [14, 0], {
                extrapolateLeft: "clamp", extrapolateRight: "clamp",
              });
              return (
                <div key={i} style={{
                  opacity: msgOpacity, transform: `translateY(${msgShift}px)`,
                  display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                }}>
                  <div style={{
                    maxWidth: "82%",
                    padding: "9px 14px", borderRadius: msg.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                    background: msg.role === "user" ? `${C.accent}18` : C.surfaceRaised,
                    border: msg.role === "user" ? `1px solid ${C.accent}30` : `1px solid ${C.lineStrong}`,
                    fontFamily: F.sans, fontSize: 12.5,
                    color: msg.role === "user" ? C.ink : C.inkMuted,
                    lineHeight: 1.55,
                  }}>
                    {msg.text}
                    {msg.ref && (
                      <div style={{
                        marginTop: 6,
                        fontFamily: F.mono, fontSize: 10.5,
                        color: C.accent, opacity: 0.85,
                      }}>
                        ↗ {msg.ref}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
