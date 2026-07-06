"""Adapter for GajuuzZ AlphaPose + ST-GCN fall detector.

Skeleton-based action recognition (rodzina GCN): Tiny-YOLOv3 (person detection)
-> SPPE FastPose / AlphaPose (2D skeleton) -> SORT-style tracker (30-frame buffer)
-> ST-GCN (TSSTG, 7-class action). A frame is marked as a fall when any confirmed
track's predicted action == 'Fall Down'. The framework aggregates per-frame
`fall_detected` into `fall_frames` for the clip-level verdict (min_fall_frames).

Pipeline mirrors the upstream repo's main.py loop verbatim:
    https://github.com/GajuuzZ/Human-Falling-Detect-Tracks

NOTE (integracja): adapter napisany wg udokumentowanego API main.py. Po sklonowaniu
repo do repo/ należy zweryfikować, że sygnatury (SPPE_FastPose, Tracker,
Detection, TSSTG) zgadzają się z kodem — drobne różnice wersji mogą wymagać korekty.
"""

import os
import sys
import time

import cv2
import numpy as np
import torch

from core.base_detector import BaseDetector
from core.models import (
    DetectionRequest, DetectionResponse,
    FrameResult, PersonDetection, BoundingBox,
    FallState, InputType,
)

# Upstream repo (cloned into repo/) must be importable.
_REPO = os.path.join(os.path.dirname(__file__), 'repo')
if not os.path.isdir(_REPO):
    _REPO = '/app/repo'
sys.path.insert(0, _REPO)

# Upstream code predates torch 2.6 (weights_only default flipped to True).
# Weights come from a known repo and are trusted -> restore legacy load behaviour.
_torch_load_orig = torch.load
def _torch_load_legacy(*a, **k):
    k.setdefault('weights_only', False)
    return _torch_load_orig(*a, **k)
torch.load = _torch_load_legacy

from DetectorLoader import TinyYOLOv3_onecls          # noqa: E402
from PoseEstimateLoader import SPPE_FastPose           # noqa: E402
from Track.Tracker import Detection, Tracker           # noqa: E402
from ActionsEstLoader import TSSTG                      # noqa: E402


def kpt2bbox(kpt, ex=20):
    """Bounding box that holds all keypoints (x, y) — from upstream main.py."""
    return np.array((kpt[:, 0].min() - ex, kpt[:, 1].min() - ex,
                     kpt[:, 0].max() + ex, kpt[:, 1].max() + ex))


class GajuuzzStgcnDetector(BaseDetector):
    """AlphaPose skeleton + Spatial-Temporal GCN action recognition."""

    @property
    def name(self) -> str:
        return 'gajuuzz_stgcn'

    @property
    def version(self) -> str:
        return '1.0.0'

    @property
    def supported_input_types(self):
        return [InputType.VIDEO]

    @property
    def multi_person(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False  # CPU works but is slow; GPU strongly recommended

    def initialize(self) -> None:
        """Load Tiny-YOLO (person), SPPE FastPose (skeleton), ST-GCN (action)."""
        # Upstream loaders use paths relative to the repo root (e.g. 'Models/...').
        os.chdir(_REPO)
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'

        inp_dets = int(self.config.get('inp_dets', 384))
        pose_backbone = self.config.get('pose_backbone', 'resnet50')
        # upstream defaults: inp_pose = (224, 160)
        self._action_window = 30

        self._detect_model = TinyYOLOv3_onecls(inp_dets, device=self._device)
        self._pose_model = SPPE_FastPose(pose_backbone, 224, 160, device=self._device)
        self._action_model = TSSTG(device=self._device)

        self._initialized = True

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        """Run the full skeleton->GCN pipeline frame-by-frame."""
        start_time = time.time()

        cfg = request.config or {}
        frame_skip = int(cfg.get('frame_skip', 1))

        # Tracker holds state across frames -> fresh instance per video.
        tracker = Tracker(max_age=30, n_init=3)

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise ValueError(f'Failed to open video: {request.input_path}')

        frame_results = []
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_idx = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                if frame_skip > 1 and frame_idx % frame_skip != 0:
                    frame_idx += 1
                    continue

                # 1. person detection (Tiny-YOLO one-class).
                # need_resize=True: loader resizes to input_size internally and scales
                # boxes back to original-frame coords (we keep the whole pipeline in
                # original coords, unlike upstream main.py which works on resized frames).
                detected = self._detect_model.detect(frame, need_resize=True, expand_bb=10)

                # 2. tracker predict + re-feed predicted boxes (upstream trick)
                tracker.predict()
                for track in tracker.tracks:
                    det = torch.tensor(
                        [track.to_tlbr().tolist() + [0.5, 1.0, 0.0]],
                        dtype=torch.float32,
                    )
                    detected = torch.cat([detected, det], dim=0) if detected is not None else det

                # 3. pose estimation -> Detection objects for the tracker
                detections = []
                if detected is not None:
                    poses = self._pose_model.predict(frame, detected[:, 0:4], detected[:, 4])
                    detections = [
                        Detection(
                            kpt2bbox(ps['keypoints'].numpy()),
                            np.concatenate(
                                (ps['keypoints'].numpy(), ps['kp_score'].numpy()), axis=1),
                            ps['kp_score'].mean().numpy(),
                        )
                        for ps in poses
                    ]

                # 4. tracker update
                tracker.update(detections)

                # 5. ST-GCN action per confirmed track with a full 30-frame window
                persons = []
                fall_detected = False
                for track in tracker.tracks:
                    if not track.is_confirmed():
                        continue

                    action_name = 'pending'
                    fall_conf = 0.0
                    if len(track.keypoints_list) == self._action_window:
                        pts = np.array(track.keypoints_list, dtype=np.float32)
                        out = self._action_model.predict(pts, frame.shape[:2])
                        action_name = self._action_model.class_names[out[0].argmax()]
                        if action_name == 'Fall Down':
                            fall_detected = True
                            fall_conf = float(out[0].max())

                    tlbr = track.to_tlbr().astype(float)
                    is_fall = action_name == 'Fall Down'
                    persons.append(PersonDetection(
                        person_id=str(track.track_id),
                        bbox=BoundingBox(
                            x_min=float(tlbr[0]), y_min=float(tlbr[1]),
                            x_max=float(tlbr[2]), y_max=float(tlbr[3]),
                            confidence=1.0,
                        ),
                        fall_state=FallState.FALL_DETECTED if is_fall else FallState.NO_FALL,
                        fall_confidence=fall_conf,
                        activity_label=action_name,
                    ))

                frame_results.append(FrameResult(
                    frame_index=frame_idx,
                    timestamp_ms=timestamp_ms,
                    persons=persons,
                    fall_detected=fall_detected,
                ))
                frame_idx += 1

        finally:
            cap.release()

        processing_time_ms = (time.time() - start_time) * 1000
        effective_config = {
            'frame_skip': frame_skip,
            'action_window': self._action_window,
        }

        return self._build_response(
            task_id=request.task_id,
            input_type=request.input_type,
            frame_results=frame_results,
            total_frames=total_frames if total_frames > 0 else frame_idx,
            processed_frames=len(frame_results),
            processing_time_ms=processing_time_ms,
            config_used=effective_config,
            meta={
                'detector': self.name,
                'model': 'TinyYOLOv3-onecls + SPPE FastPose(resnet50) + ST-GCN (TSSTG)',
                'architecture': 'AlphaPose skeleton + Spatial-Temporal GCN action recognition (7 classes)',
                'device': self._device,
                'action_window_frames': self._action_window,
                'video_fps': fps,
            },
        )

    def cleanup(self) -> None:
        """Release model resources."""
        for attr in ('_detect_model', '_pose_model', '_action_model'):
            if hasattr(self, attr):
                setattr(self, attr, None)
