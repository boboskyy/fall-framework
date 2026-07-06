# FallFW - a framework for comparing vision-based fall detectors

A microservice research framework: every fall detector runs as a Docker
container behind a unified REST API, so different algorithms can be executed on
the same recordings and compared fairly - at the frame, clip and dataset level.
Built for a master's thesis on cross-dataset generalization of vision-based
fall detection.

Author: Karol Bobowski

| Evaluation lab | Detectors | Datasets |
|---|---|---|
| ![Lab](docs/screenshots/lab.png) | ![Detectors](docs/screenshots/detectors.png) | ![Datasets](docs/screenshots/datasets.png) |

## Features

- live detector ranking (F1, recall, FPR, precision) on a selected dataset,
- sensitivity analysis of the `min_fall_frames` aggregation threshold (ranking flips),
- cross-dataset matrix: F1 per detector × dataset with ranks,
- ensemble diversity measures (Cohen's kappa, double-fault, error co-occurrence matrix),
- data leakage map (train / eval / OOD for detector–dataset pairs),
- clip browser with per-frame decisions and frame jumping,
- PL/EN interface, light/dark theme, built-in tutorial.

## Quick start

```bash
git clone https://github.com/boboskyy/fall-framework.git
cd fall-framework
python3 launch.py
```

The launcher builds and starts the **Gateway** (port 3000) and the **Frontend**
(port 2999) - open http://localhost:2999.

Working with detectors via the CLI (optionally `pip install click requests rich simple-term-menu`):

```bash
python -m cli download --all      # fetch detector code (GitHub Releases)
python -m cli build --all         # build Docker images
python -m cli start <name>
python -m cli detect video.mp4 -d <name> --sync
```

Interactive mode: `python -m cli` (arrow-key navigation).

## Detectors (11, six method categories)

| Detector | Category | Technology | Original repository |
|----------|----------|------------|---------------------|
| boboskyy_fall_detect | A - pose + LSTM | MediaPipe + LSTM | [archive](https://github.com/boboskyy/fall-detector-repos) |
| taufeeque_human_fall | A - pose + LSTM | OpenPifPaf + LSTM | [taufeeque9/HumanFallDetection](https://github.com/taufeeque9/HumanFallDetection) |
| parichehrvn_tcn_fall | B - pose + TCN | YOLOv11-Pose + TCN | [parichehrvn/fall_detection](https://github.com/parichehrvn/fall_detection) |
| barkhaaroraa_fall_detection_dl | C - pose + heuristics | MediaPipe, shoulder-drop rule | [barkhaaroraa/health_monitoring_system_DL](https://github.com/barkhaaroraa/health_monitoring_system_DL) |
| cwlroda_openpifpaf | C - pose + heuristics | OpenPifPaf + centroid tracker | [cwlroda/falldetection_openpifpaf](https://github.com/cwlroda/falldetection_openpifpaf) |
| itskyledc_yolov12_mediapipe | C - pose + heuristics | YOLOv12 + MediaPipe, rule-based | [itSkyyledc/Human-Fall-Detection-Yolov12-Mediapipe](https://github.com/itSkyyledc/Human-Fall-Detection-Yolov12-Mediapipe) |
| yb_class_fall | C - pose + heuristics | YOLOv7-w6-pose, biomechanics | [Y-B-Class-Projects/Human-Fall-Detection](https://github.com/Y-B-Class-Projects/Human-Fall-Detection) |
| noorkhokhar_yolov8_fall | D - object detection | YOLOv8, "fall" class | [noorkhokhar99/Fall_Detection_Using_Yolov8](https://github.com/noorkhokhar99/Fall_Detection_Using_Yolov8) |
| tonlongthuat_fall_detection | D - object detection | YOLOv8-pose, "fall" class | [tonlongthuat/Real-Time-Fall-Detection](https://github.com/tonlongthuat/Real-Time-Fall-Detection) |
| dzungvpham_twostream_cnn | E - two-stream | MobileNetV2 + Motion History Image | [dzungvpham/fall-detection-two-stream-cnn](https://github.com/dzungvpham/fall-detection-two-stream-cnn) |
| gajuuzz_stgcn | F - skeleton graph (GCN) | AlphaPose/SPPE + ST-GCN (TSSTG) | [GajuuzZ/Human-Falling-Detect-Tracks](https://github.com/GajuuzZ/Human-Falling-Detect-Tracks) |

Detector code is downloaded as packaged archives from
[boboskyy/fall-detector-repos](https://github.com/boboskyy/fall-detector-repos)
(GitHub Releases); model weights - as described in each detector's README.

## Datasets

| Dataset | Source |
|---------|--------|
| URFD (UR Fall Detection) | [fenix.ur.edu.pl/~mkepski/ds/uf.html](http://fenix.ur.edu.pl/~mkepski/ds/uf.html) |
| GMDCSA-24 | [ekramalam/GMDCSA24…](https://github.com/ekramalam/GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos) |
| CAUCAFall | [Mendeley Data, doi:10.17632/7w7fccy7ky.5](https://doi.org/10.17632/7w7fccy7ky.5) |
| MCFD (Multiple Cameras Fall) | [iro.umontreal.ca/~labimage/Dataset](https://www.iro.umontreal.ca/~labimage/Dataset/) |

Prepared clip bundles (with clip-level labels) are downloaded from GitHub
Releases (`datasets-v1`); you can also add **your own dataset** - upload a
folder of clips via the UI (Datasets tab) or the gateway API.

## Adding your own detector

A detector is a folder in `detectors/` following the `detectors/_template`
scaffold: `manifest.json` (metadata, port), `detector.py` (an adapter extending
`BaseDetector`), `app.py`, `Dockerfile`, `requirements.txt`. Once added, it
shows up in the CLI and the UI like any other detector.

## Project layout

```
fall-framework/
├── core/           shared library (models, BaseDetector, Flask factory)
├── gateway/        REST API + orchestration and evaluation stats (port 3000)
├── frontend/       static SPA (vanilla JS) served by nginx (port 2999)
├── cli/            command-line interface (Click)
├── detectors/      detector adapters + _template scaffold
├── shared/         shared Docker volume (uploads, results, state)
└── launch.py       launcher (build + up)
```
