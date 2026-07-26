import { Composition } from "remotion";
import { TOTAL_DURATION } from "./constants";
import { DeepDocVideo } from "./DeepDocVideo";

export const RemotionRoot = () => {
  return (
    <Composition
      id="DeepDocVideo"
      component={DeepDocVideo}
      durationInFrames={TOTAL_DURATION}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
