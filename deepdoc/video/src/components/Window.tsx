import type { CSSProperties, ReactNode } from "react";
import { C, F } from "../constants";

/** The window chrome used across the site: three quiet dots and a mono title. */
export const Window = ({ title, width, height, children, style, light }: {
  title: ReactNode; width: number; height: number; children: ReactNode; style?: CSSProperties; light?: boolean;
}) => {
  const bar = light ? "#ECEAE4" : C.surfaceRaised;
  const dot = light ? "rgba(17,17,16,0.16)" : C.lineStrong;
  return (
    <div
      style={{
        width, height, borderRadius: 18, overflow: "hidden", display: "flex", flexDirection: "column",
        background: light ? "#FFFFFF" : C.surface,
        border: `1px solid ${C.lineStrong}`,
        boxShadow: "0 50px 120px -30px rgba(0,0,0,0.85), inset 0 1px 0 rgba(236,234,227,0.06)",
        ...style,
      }}
    >
      <div style={{ height: 50, flexShrink: 0, display: "flex", alignItems: "center", gap: 9, padding: "0 20px", background: bar, borderBottom: `1px solid ${light ? "rgba(17,17,16,0.1)" : C.line}` }}>
        {[0, 1, 2].map((i) => <span key={i} style={{ width: 12, height: 12, borderRadius: 6, background: dot }} />)}
        <div style={{ flex: 1, textAlign: "center", marginRight: 54, fontFamily: F.mono, fontSize: 15, color: light ? "#63635B" : C.inkFaint }}>{title}</div>
      </div>
      <div style={{ position: "relative", flex: 1, overflow: "hidden" }}>{children}</div>
    </div>
  );
};
