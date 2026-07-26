import { AbsoluteFill, Audio, interpolate, staticFile } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { T, TOTAL_DURATION } from "./constants";
import { BuildScene } from "./scenes/BuildScene";
import { Intro } from "./scenes/Intro";
import { Outro } from "./scenes/Outro";
import { PlannerScene } from "./scenes/PlannerScene";
import { Problem } from "./scenes/Problem";
import { ResultScene } from "./scenes/ResultScene";
import { ScanScene } from "./scenes/ScanScene";
import { TerminalScene } from "./scenes/TerminalScene";

const transition = (
  <TransitionSeries.Transition
    presentation={fade()}
    timing={linearTiming({ durationInFrames: T.TRANSITION_DURATION })}
  />
);

export const DeepDocVideo = () => {
  return (
    <AbsoluteFill style={{ background: "#0a0a0a" }}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={T.INTRO_DURATION}>
          <Intro />
        </TransitionSeries.Sequence>
        {transition}
        <TransitionSeries.Sequence durationInFrames={T.PROBLEM_DURATION}>
          <Problem />
        </TransitionSeries.Sequence>
        {transition}
        <TransitionSeries.Sequence durationInFrames={T.SCAN_DURATION}>
          <ScanScene />
        </TransitionSeries.Sequence>
        {transition}
        <TransitionSeries.Sequence durationInFrames={T.PLANNER_DURATION}>
          <PlannerScene />
        </TransitionSeries.Sequence>
        {transition}
        <TransitionSeries.Sequence durationInFrames={T.GENERATE_DURATION}>
          <TerminalScene />
        </TransitionSeries.Sequence>
        {transition}
        <TransitionSeries.Sequence durationInFrames={T.BUILD_DURATION}>
          <BuildScene />
        </TransitionSeries.Sequence>
        {transition}
        <TransitionSeries.Sequence durationInFrames={T.RESULT_DURATION}>
          <ResultScene />
        </TransitionSeries.Sequence>
        {transition}
        <TransitionSeries.Sequence durationInFrames={T.OUTRO_DURATION}>
          <Outro />
        </TransitionSeries.Sequence>
      </TransitionSeries>

      {/* Background music bed — "Aitech" by Kevin MacLeod (incompetech.com),
          licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/).
          This is the only audio in the piece: the old cross-fade "whoosh"/
          "ding" cues pulled from a remote URL (remotion.media) at render
          time — a stock sound plus a network dependency that could stall
          or fail a render. Visual timing alone now carries every beat. */}
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
