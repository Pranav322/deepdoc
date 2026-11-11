// Renders the social card (public/og.jpg) from an SVG, so there is no
// screenshot master to keep in sync with the design. Run with
// `npm run images` after changing the headline or palette.
import sharp from "sharp";

const W = 1200, H = 630, CELL = 18;
const INK = "#ECEAE3", SURFACE = "#0D0D0C";

// A fixed pixel field: dim "code" runs on the left, tidy "doc" lines on the right.
let seed = 11;
const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
const cells = [];
const top = 12, rows = Math.floor(H / CELL);
for (let y = top; y < rows; y++) {
  let x = 1;
  const max = 15 + Math.floor(rnd() * 8);
  if (y % 6 === 0) continue;
  while (x < max) {
    const run = 1 + Math.floor(rnd() * 5);
    for (let i = 0; i < run && x < max; i++) cells.push([x++, y, 0.2]);
    x += 1 + (rnd() < 0.3 ? 1 : 0);
  }
  const len = 3 + Math.floor(rnd() * 12);
  for (let i = 0; i < len; i++) cells.push([36 + i, y, y % 6 === 1 ? 0.9 : 0.5]);
}
const rects = cells
  .map(([x, y, a]) => `<rect x="${x * CELL + 2}" y="${y * CELL + 2}" width="${CELL - 4}" height="${CELL - 4}" fill="${INK}" opacity="${a}"/>`)
  .join("");

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <rect width="${W}" height="${H}" fill="${SURFACE}"/>
  <defs><linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0.35" stop-color="${SURFACE}"/><stop offset="0.75" stop-color="${SURFACE}" stop-opacity="0"/></linearGradient></defs>
  ${rects}
  <rect width="${W}" height="${H * 0.78}" fill="url(#fade)"/>
  <g transform="translate(72 70)">
    <path d="M14 9 H24 A15 15 0 0 1 24 39 H14 Z M20 15 H24 A9 9 0 0 1 24 33 H20 Z" fill="${INK}" fill-rule="evenodd" transform="scale(1.25)"/>
    <text x="64" y="40" font-family="Helvetica, Arial, sans-serif" font-size="34" font-weight="700" fill="${INK}" letter-spacing="-0.5">eepDoc</text>
  </g>
  <text x="72" y="228" font-family="Helvetica, Arial, sans-serif" font-size="66" font-weight="700" fill="${INK}" letter-spacing="-2.4">Documentation that</text>
  <text x="72" y="302" font-family="Helvetica, Arial, sans-serif" font-size="66" font-weight="700" fill="${INK}" letter-spacing="-2.4">keeps pace with your</text>
  <text x="72" y="376" font-family="Georgia, serif" font-style="italic" font-size="70" fill="${INK}" letter-spacing="-1.5">codebase.</text>
  <text x="72" y="${H - 52}" font-family="Menlo, Courier, monospace" font-size="22" fill="${INK}" opacity="0.55">deepdoc.tech</text>
</svg>`;

const info = await sharp(Buffer.from(svg)).jpeg({ quality: 86, mozjpeg: true }).toFile("public/og.jpg");
console.log(`public/og.jpg  ${info.width}x${info.height}  ${(info.size / 1024).toFixed(0)} KB`);
