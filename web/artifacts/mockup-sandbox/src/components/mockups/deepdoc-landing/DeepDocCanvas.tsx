import React from "react";

function getPreviewUrl(path: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  return `${base}/preview/${path}`;
}

interface ViewportFrameProps {
  label: string;
  badge: string;
  width: number;
  height: number;
  scale: number;
  path?: string;
}

function ViewportFrame({ label, badge, width, height, scale, path = "deepdoc-landing/LandingPage" }: ViewportFrameProps) {
  const url = getPreviewUrl(path);

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-white">{label}</span>
        <span className="px-2 py-0.5 rounded-full text-xs font-mono bg-white/10 text-gray-400 border border-white/10">{badge}</span>
      </div>

      <div
        className="relative rounded-2xl overflow-hidden border border-white/10 shadow-2xl bg-[#0A0A0A]"
        style={{ width: width * scale, height: height * scale }}
      >
        <div
          style={{
            width,
            height,
            transform: `scale(${scale})`,
            transformOrigin: "top left",
            pointerEvents: "none",
            overflow: "hidden",
          }}
        >
          <iframe
            src={url}
            title={label}
            style={{
              width,
              height,
              border: "none",
              display: "block",
            }}
            scrolling="no"
          />
        </div>

        {/* Viewport width indicator at bottom */}
        <div className="absolute bottom-0 left-0 right-0 h-7 bg-gradient-to-t from-black/80 to-transparent flex items-end justify-center pb-1.5 pointer-events-none">
          <span className="text-[10px] font-mono text-gray-500">{width}px viewport</span>
        </div>
      </div>
    </div>
  );
}

export function DeepDocCanvas() {
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-start py-10 px-6 gap-10 overflow-auto"
      style={{
        background: "linear-gradient(135deg, #0d0d0d 0%, #111 100%)",
        fontFamily: "'Outfit', sans-serif",
      }}
    >
      <style dangerouslySetInnerHTML={{__html: `
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600&display=swap');
      `}} />

      {/* Header */}
      <div className="text-center max-w-2xl">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-gray-400 mb-4">
          <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF] animate-pulse"></span>
          Responsive Design Preview
        </div>
        <h1 className="text-2xl font-semibold text-white mb-2">DeepDoc Landing Page</h1>
        <p className="text-gray-500 text-sm">
          Side-by-side comparison of mobile (390px), tablet (768px), and desktop (1280px) viewports
        </p>
      </div>

      {/* Side-by-side frames */}
      <div className="flex flex-row items-start justify-start lg:justify-center gap-10 w-full max-w-screen-2xl overflow-x-auto pb-4">
        {/* Mobile viewport — 390×844 scaled to 320×695 */}
        <ViewportFrame
          label="Mobile"
          badge="iPhone 14 Pro"
          width={390}
          height={844}
          scale={320 / 390}
        />

        {/* Tablet viewport — 768×1024 scaled to ~500×667 */}
        <ViewportFrame
          label="Tablet"
          badge="iPad Mini"
          width={768}
          height={1024}
          scale={500 / 768}
        />

        {/* Desktop viewport — 1280×800 scaled to ~700×437 */}
        <ViewportFrame
          label="Desktop"
          badge="1280px"
          width={1280}
          height={800}
          scale={700 / 1280}
        />
      </div>

      {/* Additional Pages Section */}
      <div className="w-full max-w-screen-2xl mt-12 pt-12 border-t border-white/5">
        <h2 className="text-xl font-semibold text-white mb-8 text-center">Other Pages</h2>
        <div className="flex flex-col items-center justify-center">
          <ViewportFrame
            label="Documentation"
            badge="Full Width"
            width={1280}
            height={800}
            scale={0.8}
            path="deepdoc-landing/DocsPage"
          />
        </div>
      </div>
    </div>
  );
}
