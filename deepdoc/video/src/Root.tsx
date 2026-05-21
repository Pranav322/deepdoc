import { Composition } from "remotion";
import { T } from "./constants";
import { DeepDocVideo } from "./DeepDocVideo";

export const RemotionRoot = () => {
  return (
    <Composition
      id="DeepDocVideo"
      component={DeepDocVideo}
      durationInFrames={T.TOTAL}
      fps={30}
      width={1280}
      height={720}
    />
  );
};
