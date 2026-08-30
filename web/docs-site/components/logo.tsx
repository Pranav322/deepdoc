/**
 * DeepDoc brand mark, ported from web/src/components/Logo.astro so the docs
 * site and the marketing site share one identity.
 *
 * The "depth D": a geometric D with two receding echo strokes reading as
 * layers — "Deep". The mark IS the leading D, followed by "eepDoc", so the
 * lockup reads as one word with no repeated letter.
 */
const D_CONTOUR = 'M14 9 H24 A15 15 0 0 1 24 39 H14';

export function Logo() {
  return (
    <span className="dd-logo" role="img" aria-label="DeepDoc">
      <svg className="dd-mark" width={26} height={26} viewBox="0 0 48 48" fill="none" aria-hidden="true">
        <path className="dd-echo dd-echo-2" d={D_CONTOUR} transform="translate(6 6)" />
        <path className="dd-echo dd-echo-1" d={D_CONTOUR} transform="translate(3 3)" />
        <path
          className="dd-front"
          fillRule="evenodd"
          d="M14 9 H24 A15 15 0 0 1 24 39 H14 Z M20 15 H24 A9 9 0 0 1 24 33 H20 Z"
        />
      </svg>
      <span className="dd-word" aria-hidden="true">eepDoc</span>
    </span>
  );
}
