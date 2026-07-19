'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';

export default function MermaidRunner() {
  const pathname = usePathname();

  useEffect(() => {
    const nodes = document.querySelectorAll<HTMLElement>('.mermaid:not([data-processed])');
    if (!nodes.length) return;
    import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: 'neutral' });
      mermaid.run({ nodes });
    });
  }, [pathname]);

  return null;
}
