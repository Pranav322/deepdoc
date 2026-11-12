// Shared helpers for the landing page's Motion animations.
//
// Layout.astro adds html.motion before first paint (only when the visitor
// allows motion) and removes it again after 2.5s if no page script loaded.
// Importing this module cancels that fallback, so start states stay hidden
// until their animation runs. Every animated component checks motionOn()
// and leaves its markup in its finished, static state when it is false.
import { animate, inView, stagger } from "motion";

clearTimeout((window as any).__motionFallback);

export const ease = [0.22, 1, 0.36, 1] as const;
export const motionOn = () => document.documentElement.classList.contains("motion");
export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Run `play` repeatedly while `el` is on screen. `alive()` turns false when it leaves. */
export function loopInView(el: Element, play: (alive: () => boolean) => Promise<void>, amount = 0.35) {
  inView(
    el,
    () => {
      let on = true;
      (async () => {
        while (on) {
          await play(() => on);
          await sleep(60);
        }
      })();
      return () => { on = false; };
    },
    { amount }
  );
}

/** Wrap each word of an element's text in a span, keeping child elements whole. */
export function splitWords(el: HTMLElement): HTMLElement[] {
  const out: HTMLElement[] = [];
  for (const node of Array.from(el.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      const frag = document.createDocumentFragment();
      for (const part of (node.textContent ?? "").split(/(\s+)/)) {
        if (!part) continue;
        if (/^\s+$/.test(part)) { frag.append(" "); continue; }
        const span = document.createElement("span");
        span.className = "w";
        span.textContent = part;
        frag.append(span);
        out.push(span);
      }
      node.replaceWith(frag);
    } else if (node instanceof HTMLElement) {
      node.classList.add("w");
      out.push(node);
    }
  }
  return out;
}

/** Headings marked data-words arrive word by word when scrolled into view. */
export function revealWords() {
  document.querySelectorAll<HTMLElement>("[data-words]").forEach((el) => {
    const words = splitWords(el);
    words.forEach((w) => (w.style.opacity = "0"));
    el.style.opacity = "1";
    inView(el, () => {
      animate(words, { opacity: [0, 1], y: ["0.4em", "0em"], filter: ["blur(8px)", "blur(0px)"] }, { delay: stagger(0.045), duration: 0.7, ease });
    }, { amount: 0.6 });
  });
}

/** Cards marked .spot get a soft highlight that follows the pointer. */
export function spotlight() {
  document.querySelectorAll<HTMLElement>(".spot").forEach((card) => {
    card.addEventListener("pointermove", (e) => {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - r.left}px`);
      card.style.setProperty("--my", `${e.clientY - r.top}px`);
    });
  });
}
