// Renders the social card (public/og.jpg) from an SVG, so there is no
// screenshot master to keep in sync with the design. Run with
// `npm run images` after changing the headline or palette.
import sharp from "sharp";

const W = 1200, H = 630, CELL = 18;
const INK = "#ECEAE3", SURFACE = "#0D0D0C", ACCENT = "#A594FF";
const PALETTE = ["#5B8CFF", "#A78BFA", "#F472B6", "#FB923C", "#2DD4BF"];

// A fixed pixel field in the palette colours, denser towards the bottom-right.
let seed = 11;
const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
const cols = Math.ceil(W / CELL), rows = Math.ceil(H / CELL);
let rects = "";
for (let y = 0; y < rows; y++) {
  for (let x = 0; x < cols; x++) {
    const weight = (x / cols) * 0.55 + (y / rows) * 0.45;
    if (rnd() > weight * weight * 0.55) continue;
    const c = PALETTE[Math.floor(rnd() * PALETTE.length)];
    rects += `<rect x="${x * CELL + 1}" y="${y * CELL + 1}" width="${CELL - 2}" height="${CELL - 2}" fill="${c}" opacity="${(0.35 + rnd() * 0.6).toFixed(2)}"/>`;
  }
}

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <rect width="${W}" height="${H}" fill="${SURFACE}"/>
  <defs><linearGradient id="fade" x1="0" y1="0" x2="1" y2="0.6"><stop offset="0.45" stop-color="${SURFACE}"/><stop offset="0.85" stop-color="${SURFACE}" stop-opacity="0"/></linearGradient><linearGradient id="g" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#7AA2FF"/><stop offset="0.4" stop-color="#B79CFF"/><stop offset="0.75" stop-color="#F98AC4"/><stop offset="1" stop-color="#FDA35C"/></linearGradient></defs>
  ${rects}
  <rect width="${W}" height="${H}" fill="url(#fade)"/>
  <g transform="translate(72 70)">
    <path d="M14 9 H24 A15 15 0 0 1 24 39 H14 Z M20 15 H24 A9 9 0 0 1 24 33 H20 Z" fill="${ACCENT}" fill-rule="evenodd" transform="scale(1.25)"/>
    <text x="64" y="40" font-family="Helvetica, Arial, sans-serif" font-size="34" font-weight="700" fill="${INK}" letter-spacing="-0.5">eepDoc</text>
  </g>
  <text x="72" y="228" font-family="Helvetica, Arial, sans-serif" font-size="66" font-weight="700" fill="${INK}" letter-spacing="-2.4">Documentation that</text>
  <text x="72" y="302" font-family="Helvetica, Arial, sans-serif" font-size="66" font-weight="700" fill="${INK}" letter-spacing="-2.4">keeps pace with your</text>
  <text x="72" y="376" font-family="Georgia, serif" font-style="italic" font-size="70" fill="url(#g)" letter-spacing="-1.5">codebase.</text>
  <text x="72" y="${H - 52}" font-family="Menlo, Courier, monospace" font-size="22" fill="${INK}" opacity="0.55">deepdoc.tech</text>
</svg>`;

const info = await sharp(Buffer.from(svg)).jpeg({ quality: 86, mozjpeg: true }).toFile("public/og.jpg");
console.log(`public/og.jpg  ${info.width}x${info.height}  ${(info.size / 1024).toFixed(0)} KB`);
