// Real webfonts, loaded through Remotion's font loader so headless Chrome has
// them before the first frame. The same three families as deepdoc.tech.
import { loadFont as loadDMSans } from "@remotion/google-fonts/DMSans";
import { loadFont as loadJetBrainsMono } from "@remotion/google-fonts/JetBrainsMono";
import { loadFont as loadInstrumentSerif } from "@remotion/google-fonts/InstrumentSerif";

const dmSans = loadDMSans("normal", { weights: ["400", "500", "600", "700"], subsets: ["latin"] });
const jetBrainsMono = loadJetBrainsMono("normal", { weights: ["400", "500", "700"], subsets: ["latin"] });
const instrumentSerif = loadInstrumentSerif("italic", { weights: ["400"], subsets: ["latin"] });

export const FONT_SANS = dmSans.fontFamily;
export const FONT_MONO = jetBrainsMono.fontFamily;
export const FONT_SERIF = instrumentSerif.fontFamily;
