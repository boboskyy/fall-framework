"""Adapter for itskyledc YOLOv12 + MediaPipe fall detector (multi-person, heuristic)."""

import os
import sys
import time

import cv2
import numpy as np

from core.base_detector import BaseDetector
from core.models import (
    DetectionRequest, DetectionResponse,
    FrameResult, PersonDetection, Keypoint, BoundingBox,
    FallState, InputType
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'repo', 'models'))

from fall_detector import FallDetector

MEDIAPIPE_TO_COCO = {
    0: 'nose', 2: 'left_eye', 5: 'right_eye', 7: 'left_ear', 8: 'right_ear',
    11: 'left_shoulder', 12: 'right_shoulder', 13: 'left_elbow', 14: 'right_elbow',
    15: 'left_wrist', 16: 'right_wrist', 23: 'left_hip', 24: 'right_hip',
    25: 'left_knee', 26: 'right_knee', 27: 'left_ankle', 28: 'right_ankle',
}


class ItskyledcYolov12MediapipeDetector(BaseDetector):
    """
    Multi-person fall detection using YOLOv12 for person detection,
    MediaPipe Pose for 33-landmark estimation, and rule-based heuristic
    fall classification (angle + aspect ratio thresholds).
    """

    @property
    def name(self) -> str:
        return 'itskyledc_yolov12_mediapipe'

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
        return False

    def initialize(self) -> None:
        """Load YOLOv12 + MediaPipe models via FallDetector."""
        model_path = os.path.join(os.path.dirname(__file__), 'repo', 'yolov12n1.pt')
        if not os.path.exists(model_path):
            model_path = '/app/repo/yolov12n1.pt'

        self._default_confidence = self.config.get('confidence_threshold', 0.5)
        self._default_fall_threshold = self.config.get('fall_threshold', 0.4)
        self._default_angle_threshold = self.config.get('angle_threshold', 45)

        self._detector = FallDetector(
            model_path=model_path,
            confidence=self._default_confidence
        )
        self._detector.fall_threshold = self._default_fall_threshold
        self._detector.angle_threshold = self._default_angle_threshold

        self._landmark_cache = {}
        original_analyze_pose = self._detector.analyze_pose

        def caching_analyze_pose(frame, person_box):
            result = original_analyze_pose(frame, person_box)
            self._landmark_cache[tuple(person_box)] = result
            return result

        self._detector.analyze_pose = caching_analyze_pose

        self._initialized = True

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        """Process video with YOLOv12 + MediaPipe fall detection."""
        start_time = time.time()

        cfg = request.config or {}
        confidence = cfg.get('confidence_threshold', self._default_confidence)
        fall_threshold = cfg.get('fall_threshold', self._default_fall_threshold)
        angle_threshold = cfg.get('angle_threshold', self._default_angle_threshold)
        frame_skip = cfg.get('frame_skip', 1)

        self._detector.confidence = confidence
        self._detector.fall_threshold = fall_threshold
        self._detector.angle_threshold = angle_threshold

        self._detector.prev_poses = []
        self._detector.fallen_person_ids = set()
        self._detector.person_trackers = {}
        self._detector.next_person_id = 1
        self._detector.fall_detected = False
        self._detector.fall_start_time = None
        self._detector.fall_types = {k: False for k in self._detector.fall_types}

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise ValueError(f'Failed to open video: {request.input_path}')

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

            frame_results = []
            frame_idx = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

                if frame_skip > 1 and frame_idx % frame_skip != 0:
                    frame_idx += 1
                    continue

                height, width = frame.shape[:2]

                self._landmark_cache = {}

                _output_frame, falls_detected, fall_data = self._detector.process_frame(frame)

                persons = []
                person_boxes = fall_data.get('person_boxes', [])
                person_ids = fall_data.get('person_ids', [])
                fallen_ids = fall_data.get('fallen_ids', [])
                fall_type = fall_data.get('fall_type')

                for i, box in enumerate(person_boxes):
                    box_tuple = tuple(box)
                    x1, y1, x2, y2 = box

                    pid = str(person_ids[i]) if i < len(person_ids) else str(i)

                    cached = self._landmark_cache.get(box_tuple)
                    landmarks_raw = None
                    pose_features = None
                    if cached is not None:
                        landmarks_raw, pose_features = cached

                    keypoints = []
                    pose_conf = 0.0
                    if landmarks_raw:
                        visibility_scores = []
                        for mp_idx, coco_name in MEDIAPIPE_TO_COCO.items():
                            if mp_idx < len(landmarks_raw):
                                lm_x, lm_y, lm_z, lm_vis = landmarks_raw[mp_idx]
                                px = lm_x * (x2 - x1) + x1
                                py = lm_y * (y2 - y1) + y1
                                pz = lm_z * (x2 - x1)
                                keypoints.append(Keypoint(
                                    name=coco_name,
                                    x=float(px),
                                    y=float(py),
                                    z=float(pz),
                                    confidence=float(lm_vis)
                                ))
                                visibility_scores.append(lm_vis)
                        if visibility_scores:
                            pose_conf = float(np.mean(visibility_scores))

                    bbox = BoundingBox(
                        x_min=float(x1),
                        y_min=float(y1),
                        x_max=float(x2),
                        y_max=float(y2),
                        confidence=float(confidence)
                    )

                    pid_int = int(pid) if pid.isdigit() else None
                    is_fallen = pid_int is not None and pid_int in fallen_ids
                    fall_state = FallState.FALL_DETECTED if is_fallen else FallState.NO_FALL
                    fall_conf = 0.8 if is_fallen else 0.0
                    activity = fall_type if is_fallen and fall_type else ('normal' if not is_fallen else 'fall')

                    features = {}
                    if pose_features:
                        features = {
                            'angle': pose_features.get('angle', 0.0),
                            'aspect_ratio': pose_features.get('aspect_ratio', 0.0),
                            'velocity_y': pose_features.get('velocity_y', 0.0),
                            'velocity_x': pose_features.get('velocity_x', 0.0),
                            'acceleration': pose_features.get('acceleration', 0.0),
                        }

                    persons.append(PersonDetection(
                        person_id=pid,
                        bbox=bbox,
                        keypoints=keypoints,
                        fall_state=fall_state,
                        fall_confidence=fall_conf,
                        pose_confidence=pose_conf,
                        activity_label=activity,
                        features=features,
                    ))

                frame_results.append(FrameResult(
                    frame_index=frame_idx,
                    timestamp_ms=timestamp_ms,
                    persons=persons,
                    fall_detected=falls_detected,
                ))

                frame_idx += 1

        finally:
            cap.release()

        processing_time_ms = (time.time() - start_time) * 1000

        effective_config = {
            'confidence_threshold': confidence,
            'fall_threshold': fall_threshold,
            'angle_threshold': angle_threshold,
            'frame_skip': frame_skip,
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
                'model': 'yolov12n1 + mediapipe_pose',
                'architecture': 'YOLOv12n1 (person detection) + MediaPipe Pose (33 landmarks) + rule-based heuristics',
                'device': 'cpu',
                'keypoint_format': 'mediapipe_33_to_coco_17',
                'coordinate_space': 'pixel_absolute',
                'video_fps': fps,
                'angle_threshold': angle_threshold,
                'fall_threshold': fall_threshold,
            }
        )

    def cleanup(self) -> None:
        """Release MediaPipe and YOLO resources."""
        if hasattr(self, '_detector') and self._detector is not None:
            if hasattr(self._detector, 'pose') and self._detector.pose is not None:
                self._detector.pose.close()
            if hasattr(self._detector, 'model'):
                del self._detector.model
            self._detector = None
