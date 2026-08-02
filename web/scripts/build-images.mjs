// Pre-optimizes the hero screenshots and the OG card from the masters in
// src/assets/ into public/. Run with `npm run images` after replacing a master.
//
// Why offline instead of astro:assets <Image>: index.astro is server-rendered
// (see the comment at the top of that file), and @astrojs/cloudflare's
// imageService can only optimize on *prerendered* pages — Cloudflare has no
// sharp at runtime. Static WebP + a hand-written srcset sidesteps that.
import sharp from "sharp";

const HERO_WIDTHS = [1104, 2208]; // hero renders at <=1104 CSS px (max-w-6xl - px-6)

// The two masters are separate screenshots and differ by a couple of pixels
// (3456x1926 vs 3454x1924). Pin one ratio so both variants emit identical
// dimensions — otherwise the light/dark <img> tags carry mismatched
// width/height attributes. object-fit: cover absorbs the ~1px crop.
const HERO_RATIO = 3456 / 1926;

const heroes = [
  { src: "src/assets/proof-docs-dark.png", out: "public/proof-docs-dark" },
  { src: "src/assets/proof-docs.png", out: "public/proof-docs" },
];

for (const { src, out } of heroes) {
  for (const w of HERO_WIDTHS) {
    const info = await sharp(src)
      .resize({ width: w, height: Math.round(w / HERO_RATIO), fit: "cover" })
      .webp({ quality: 72 })
      .toFile(`${out}-${w}.webp`);
    console.log(`${out}-${w}.webp  ${info.width}x${info.height}  ${(info.size / 1024).toFixed(0)} KB`);
  }
}

// OG card: crop to the top-left so the docs content stays legible at 1200x630,
// wide enough that no paragraph gets sliced mid-sentence.
const og = await sharp("src/assets/proof-docs-dark.png")
  .extract({ left: 0, top: 0, width: 2900, height: 1522 })
  .resize(1200, 630)
  .jpeg({ quality: 82, mozjpeg: true })
  .toFile("public/og.jpg");
console.log(`public/og.jpg  ${og.width}x${og.height}  ${(og.size / 1024).toFixed(0)} KB`);
