import { AbsoluteFill, Sequence } from "remotion";
import { T } from "./constants";
import { Intro } from "./scenes/Intro";
import { Outro } from "./scenes/Outro";
import { PipelineScene } from "./scenes/PipelineScene";
import { Problem } from "./scenes/Problem";
import { ResultScene } from "./scenes/ResultScene";
import { TerminalScene } from "./scenes/TerminalScene";

export const DeepDocVideo = () => {
  return (
    <AbsoluteFill style={{ background: "#0a0a0a" }}>
      <Sequence durationInFrames={T.INTRO_DURATION}>
        <Intro />
      </Sequence>

      <Sequence from={T.PROBLEM_START} durationInFrames={T.PROBLEM_DURATION}>
        <Problem />
      </Sequence>

      <Sequence from={T.TERMINAL_START} durationInFrames={T.TERMINAL_DURATION}>
        <TerminalScene />
      </Sequence>

      <Sequence from={T.PIPELINE_START} durationInFrames={T.PIPELINE_DURATION}>
        <PipelineScene />
      </Sequence>

      <Sequence from={T.RESULT_START} durationInFrames={T.RESULT_DURATION}>
        <ResultScene />
      </Sequence>

      <Sequence from={T.OUTRO_START} durationInFrames={T.OUTRO_DURATION}>
        <Outro />
      </Sequence>
    </AbsoluteFill>
  );
};
