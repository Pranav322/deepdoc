// Real webfonts, loaded via Remotion's font loader so Chrome headless has
// them ready before the first frame renders. Without this, every scene
// silently falls back to Arial/Helvetica Bold — which is the single biggest
// reason the old render looked like a slideshow instead of a product video.
import { loadFont as loadDMSans } from "@remotion/google-fonts/DMSans";
import { loadFont as loadJetBrainsMono } from "@remotion/google-fonts/JetBrainsMono";
import { loadFont as loadDMSerifDisplay } from "@remotion/google-fonts/DMSerifDisplay";

const dmSans = loadDMSans("normal", {
  weights: ["400", "500", "600", "700", "800", "900"],
  subsets: ["latin"],
});

const jetBrainsMono = loadJetBrainsMono("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

const dmSerifDisplay = loadDMSerifDisplay("normal", {
  weights: ["400"],
  subsets: ["latin"],
});

export const FONT_SANS = dmSans.fontFamily;
export const FONT_MONO = jetBrainsMono.fontFamily;
export const FONT_DISPLAY = dmSerifDisplay.fontFamily;

// Root.tsx awaits this once before mounting the composition list.
export const fontsReady = Promise.all([
  dmSans.waitUntilDone(),
  jetBrainsMono.waitUntilDone(),
  dmSerifDisplay.waitUntilDone(),
]);
