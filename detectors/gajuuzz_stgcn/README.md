# gajuuzz_stgcn - ST-GCN (AlphaPose + TSSTG)

Adapter for the fall detector from [GajuuzZ/Human-Falling-Detect-Tracks](https://github.com/GajuuzZ/Human-Falling-Detect-Tracks).

Pipeline: Tiny-YOLO (person detection) → SPPE FastPose (2D pose) → SORT tracker
(30-frame buffer) → ST-GCN/TSSTG (action classification). A frame is marked as a
fall when the tracked object's action is `Fall Down`; temporal aggregation is
handled by the framework-wide `min_fall_frames` threshold.

## Prerequisites (before build)

The upstream repo and model weights are not versioned here - populate the
`repo/` directory locally:

```bash
cd detectors/gajuuzz_stgcn
git clone https://github.com/GajuuzZ/Human-Falling-Detect-Tracks repo
```

Then download the weights into `repo/Models/` (Google Drive links in the
upstream README): Tiny-YOLO one-class, SPPE FastPose (ResNet50) and
`tsstg-model.pth` (ST-GCN). The paths are hard-coded in the upstream
`DetectorLoader.py` / `PoseEstimateLoader.py` / `ActionsEstLoader.py`.

## Build and run

```bash
fallfw build gajuuzz_stgcn     # GPU build: DEVICE=gpu
fallfw start gajuuzz_stgcn
fallfw detect video.mp4 -d gajuuzz_stgcn --sync
```

Note: the classifier operates on a ~30-frame window per tracked object - very
short clips (< 30 frames) will not produce a decision.
