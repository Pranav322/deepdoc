'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';

// Mermaid's own theme names. 'neutral' reads well on light backgrounds but is
// unreadable on dark ones, which is why the theme has to follow the site.
const LIGHT_THEME = 'neutral';
const DARK_THEME = 'dark';

function isDark(): boolean {
  return document.documentElement.classList.contains('dark');
}

/** Render every unprocessed diagram, stashing its source so it can re-render. */
async function renderAll(force = false) {
  const nodes = Array.from(
    document.querySelectorAll<HTMLElement>(force ? '.mermaid' : '.mermaid:not([data-processed])'),
  );
  if (!nodes.length) return;

  for (const node of nodes) {
    // mermaid replaces the element's content with an <svg>, destroying the
    // graph source. Keep a copy so a theme change can re-render from it.
    if (!node.dataset.src) node.dataset.src = node.textContent ?? '';
    if (force) {
      node.textContent = node.dataset.src;
      node.removeAttribute('data-processed');
    }
  }

  const { default: mermaid } = await import('mermaid');
  mermaid.initialize({
    startOnLoad: false,
    theme: isDark() ? DARK_THEME : LIGHT_THEME,
  });
  try {
    await mermaid.run({ nodes });
  } catch {
    // A malformed diagram must never take the page down; mermaid leaves its
    // own error text in place.
  }
}

export default function MermaidRunner() {
  const pathname = usePathname();
  const [zoomed, setZoomed] = useState<string | null>(null);

  // Initial render, and again whenever the route changes.
  useEffect(() => {
    void renderAll();
  }, [pathname]);

  // Re-render on light/dark toggle. Fumadocs flips `.dark` on <html>.
  useEffect(() => {
    let last = isDark();
    const observer = new MutationObserver(() => {
      const now = isDark();
      if (now !== last) {
        last = now;
        void renderAll(true);
      }
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });
    return () => observer.disconnect();
  }, []);

  // Click a diagram to open it full screen.
  useEffect(() => {
    function onClick(event: MouseEvent) {
      const target = event.target as HTMLElement | null;
      const host = target?.closest<HTMLElement>('.mermaid');
      if (!host) return;
      const svg = host.querySelector('svg');
      if (svg) setZoomed(svg.outerHTML);
    }
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);

  if (!zoomed) return null;
  return <MermaidLightbox svg={zoomed} onClose={() => setZoomed(null)} />;
}

const MIN_SCALE = 0.25;
const MAX_SCALE = 8;

function clamp(value: number) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
}

function MermaidLightbox({ svg, onClose }: { svg: string; onClose: () => void }) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  const reset = useCallback(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
      if (event.key === '0') reset();
      if (event.key === '+' || event.key === '=') setScale(s => clamp(s * 1.25));
      if (event.key === '-') setScale(s => clamp(s / 1.25));
    }
    document.addEventListener('keydown', onKey);
    // Stop the page scrolling behind the overlay.
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose, reset]);

  function onWheel(event: React.WheelEvent) {
    event.preventDefault();
    setScale(s => clamp(s * (event.deltaY < 0 ? 1.12 : 1 / 1.12)));
  }

  function onPointerDown(event: React.PointerEvent) {
    (event.target as Element).setPointerCapture?.(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y };
  }

  function onPointerMove(event: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    setOffset({ x: d.ox + (event.clientX - d.x), y: d.oy + (event.clientY - d.y) });
  }

  function onPointerUp() {
    drag.current = null;
  }

  return (
    <div
      className="dd-mermaid-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Diagram, full screen"
      onClick={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="dd-mermaid-tools" role="toolbar" aria-label="Diagram zoom">
        <button type="button" onClick={() => setScale(s => clamp(s / 1.25))} aria-label="Zoom out">−</button>
        <span className="dd-mermaid-scale">{Math.round(scale * 100)}%</span>
        <button type="button" onClick={() => setScale(s => clamp(s * 1.25))} aria-label="Zoom in">+</button>
        <button type="button" onClick={reset} aria-label="Reset zoom">Reset</button>
        <button type="button" onClick={onClose} aria-label="Close full screen">✕</button>
      </div>
      <div
        className="dd-mermaid-stage"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div
          className="dd-mermaid-canvas"
          style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  );
}
