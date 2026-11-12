import { AbsoluteFill, Audio, Sequence, interpolate, staticFile } from "remotion";
import { Backdrop } from "./components/Backdrop";
import { BROWSER_START, OUTRO_START, T, TOTAL_DURATION } from "./constants";
import { Browser } from "./scenes/Browser";
import { Outro } from "./scenes/Outro";
import { Terminal } from "./scenes/Terminal";

/**
 * One continuous piece: a real `deepdoc generate` run in a terminal, the real
 * site it produced opening over it, then the sign-off. No title cards.
 */
export const DeepDocVideo = () => {
  return (
    <AbsoluteFill>
      <Backdrop />
      <Sequence durationInFrames={T.TERMINAL}><Terminal /></Sequence>
      <Sequence from={BROWSER_START} durationInFrames={T.BROWSER}><Browser /></Sequence>
      <Sequence from={OUTRO_START} durationInFrames={T.OUTRO}><Outro /></Sequence>

      {/* Music: "Aitech" by Kevin MacLeod (incompetech.com), CC BY 3.0. See
          CREDITS.md. The site plays this video muted. */}
      <Audio
        src={staticFile("audio/bg-music.mp3")}
        volume={(f) =>
          0.16 *
          interpolate(f, [0, 20], [0, 1], { extrapolateRight: "clamp" }) *
          interpolate(f, [TOTAL_DURATION - 30, TOTAL_DURATION], [1, 0], { extrapolateLeft: "clamp" })
        }
      />
    </AbsoluteFill>
  );
};
