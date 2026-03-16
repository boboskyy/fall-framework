"""Adapter for barkhaaroraa fall_detection_DL detector (MediaPipe Pose + Heuristic)."""

import time
import cv2
import numpy as np
import mediapipe as mp
from typing import List, Dict, Any

from core.base_detector import BaseDetector
from core.models import (
    DetectionRequest, DetectionResponse, DetectionStatus,
    FrameResult, PersonDetection, Keypoint, BoundingBox,
    FallState, InputType
)

MEDIAPIPE_LANDMARK_NAMES = [
    'nose', 'left_eye_inner', 'left_eye', 'left_eye_outer',
    'right_eye_inner', 'right_eye', 'right_eye_outer',
    'left_ear', 'right_ear', 'mouth_left', 'mouth_right',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_pinky', 'right_pinky',
    'left_index', 'right_index', 'left_thumb', 'right_thumb',
    'left_hip', 'right_hip', 'left_knee', 'right_knee',
    'left_ankle', 'right_ankle', 'left_heel', 'right_heel',
    'left_foot_index', 'right_foot_index'
]

COCO_17_FROM_MEDIAPIPE = {
    0: 'nose', 2: 'left_eye', 5: 'right_eye', 7: 'left_ear', 8: 'right_ear',
    11: 'left_shoulder', 12: 'right_shoulder', 13: 'left_elbow', 14: 'right_elbow',
    15: 'left_wrist', 16: 'right_wrist', 23: 'left_hip', 24: 'right_hip',
    25: 'left_knee', 26: 'right_knee', 27: 'left_ankle', 28: 'right_ankle',
}


def _detect_fall_heuristic(
    avg_shoulder_y: float,
    previous_avg_shoulder_y: float,
    fall_multiplier: float = 1.5
) -> bool:
    """
    Reimplementation of main.py:34-54 detectFall() heuristic.
    Returns True if shoulder dropped by more than fall_multiplier × previous.
    In image coordinates Y increases downward, so larger Y = lower position.
    """
    if previous_avg_shoulder_y <= 0:
        return False
    fall_threshold = previous_avg_shoulder_y * fall_multiplier
    return avg_shoulder_y > fall_threshold


class BarkhaaroraaFallDetectionDlDetector(BaseDetector):

    @property
    def name(self) -> str:
        return 'barkhaaroraa_fall_detection_dl'

    @property
    def version(self) -> str:
        return '1.0.0'

    @property
    def supported_input_types(self) -> list:
        return [InputType.VIDEO]

    @property
    def multi_person(self) -> bool:
        return False

    @property
    def requires_gpu(self) -> bool:
        return False

    def initialize(self) -> None:
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            min_detection_confidence=self.config.get('min_detection_confidence', 0.7),
            min_tracking_confidence=self.config.get('min_tracking_confidence', 0.5),
            model_complexity=self.config.get('model_complexity', 2)
        )
        self._fall_multiplier = self.config.get('fall_multiplier', 1.5)
        self._check_interval_sec = self.config.get('check_interval_sec', 2.0)
        self._initialized = True

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        start_time = time.time()

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            return self._build_response(
                task_id=request.task_id,
                status=DetectionStatus.FAILED,
                frame_results=[],
                total_frames=0,
                processed_frames=0,
                fall_events=[],
                processing_time_ms=0,
                error_message=f'Failed to open video: {request.input_path}'
            )

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        fall_multiplier = request.config.get(
            'fall_multiplier', self._fall_multiplier
        ) if request.config else self._fall_multiplier
        check_interval = request.config.get(
            'check_interval_sec', self._check_interval_sec
        ) if request.config else self._check_interval_sec

        check_frame_interval = max(1, int(fps * check_interval))

        self._pose.close()
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            min_detection_confidence=self.config.get('min_detection_confidence', 0.7),
            min_tracking_confidence=self.config.get('min_tracking_confidence', 0.5),
            model_complexity=self.config.get('model_complexity', 2)
        )

        frame_results: List[FrameResult] = []
        fall_events: List[Dict[str, Any]] = []
        frame_idx = 0

        previous_avg_shoulder_y = 0.0
        fall_detected = False
        last_check_frame = -check_frame_interval

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            height, width, _ = frame.shape

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._pose.process(frame_rgb)

            persons: List[PersonDetection] = []
            fall_in_frame = fall_detected

            if results.pose_landmarks:
                mp_landmarks = results.pose_landmarks.landmark

                keypoints: List[Keypoint] = []
                for i, lm in enumerate(mp_landmarks):
                    kp_name = COCO_17_FROM_MEDIAPIPE.get(i, MEDIAPIPE_LANDMARK_NAMES[i])
                    keypoints.append(Keypoint(
                        name=kp_name,
                        x=float(lm.x * width),
                        y=float(lm.y * height),
                        z=float(lm.z * width),
                        confidence=float(lm.visibility)
                    ))

                xs = [lm.x * width for lm in mp_landmarks]
                ys = [lm.y * height for lm in mp_landmarks]
                bbox = BoundingBox(
                    x_min=float(min(xs)),
                    y_min=float(min(ys)),
                    x_max=float(max(xs)),
                    y_max=float(max(ys)),
                    confidence=float(np.mean([lm.visibility for lm in mp_landmarks]))
                )

                left_shoulder_y = float(mp_landmarks[11].y * height)
                right_shoulder_y = float(mp_landmarks[12].y * height)
                avg_shoulder_y = (left_shoulder_y + right_shoulder_y) / 2.0

                if (frame_idx - last_check_frame) >= check_frame_interval:
                    is_fall = _detect_fall_heuristic(
                        avg_shoulder_y,
                        previous_avg_shoulder_y,
                        fall_multiplier
                    )
                    if is_fall:
                        fall_detected = True
                    else:
                        fall_detected = False
                    previous_avg_shoulder_y = avg_shoulder_y
                    last_check_frame = frame_idx

                if previous_avg_shoulder_y > 0:
                    shoulder_ratio = avg_shoulder_y / (previous_avg_shoulder_y * fall_multiplier)
                    pseudo_confidence = min(1.0, max(0.0, shoulder_ratio))
                else:
                    pseudo_confidence = 0.0

                fall_state = FallState.FALL_DETECTED if fall_detected else FallState.NO_FALL
                fall_in_frame = fall_detected

                person = PersonDetection(
                    person_id='0',
                    bbox=bbox,
                    keypoints=keypoints,
                    fall_state=fall_state,
                    fall_confidence=pseudo_confidence if fall_detected else (1.0 - pseudo_confidence),
                    pose_confidence=float(np.mean([lm.visibility for lm in mp_landmarks])),
                    activity_label='falling' if fall_detected else 'not_falling',
                    features={
                        'avg_shoulder_y': avg_shoulder_y,
                        'previous_avg_shoulder_y': previous_avg_shoulder_y,
                        'fall_threshold': previous_avg_shoulder_y * fall_multiplier,
                        'shoulder_ratio': shoulder_ratio if previous_avg_shoulder_y > 0 else 0.0,
                        'left_shoulder_y': left_shoulder_y,
                        'right_shoulder_y': right_shoulder_y,
                    }
                )
                persons.append(person)
            else:
                fall_in_frame = False

            fr = FrameResult(
                frame_index=frame_idx,
                timestamp_ms=timestamp_ms,
                persons=persons,
                fall_detected=fall_in_frame,
                raw_output={
                    'pose_detected': len(persons) > 0,
                    'fall_detected': fall_in_frame,
                    'previous_avg_shoulder_y': previous_avg_shoulder_y,
                } if persons else None
            )
            frame_results.append(fr)

            if fall_in_frame and (
                len(fall_events) == 0 or
                not fall_events[-1].get('_ongoing', False)
            ):
                fall_events.append({
                    'frame_index': frame_idx,
                    'timestamp_ms': timestamp_ms,
                    'persons': ['0'],
                    '_ongoing': True
                })
            elif not fall_in_frame and len(fall_events) > 0:
                if fall_events[-1].get('_ongoing'):
                    fall_events[-1]['_ongoing'] = False

            frame_idx += 1

        cap.release()

        for evt in fall_events:
            evt.pop('_ongoing', None)

        processing_time_ms = (time.time() - start_time) * 1000
        processed_count = len(frame_results)
        fall_frame_count = sum(1 for fr in frame_results if fr.fall_detected)

        effective_config = {
            'fall_multiplier': fall_multiplier,
            'check_interval_sec': check_interval
        }

        return self._build_response(
            task_id=request.task_id,
            status=DetectionStatus.COMPLETED,
            frame_results=frame_results,
            total_frames=total_frames if total_frames > 0 else frame_idx,
            processed_frames=processed_count,
            fall_events=fall_events,
            processing_time_ms=processing_time_ms,
            config_used=effective_config,
            summary={
                'total_frames_analyzed': processed_count,
                'fall_frames_count': fall_frame_count,
                'fall_percentage': (
                    (fall_frame_count / processed_count * 100)
                    if processed_count > 0 else 0
                ),
                'fps': fps,
                'check_interval_frames': check_frame_interval,
                'fall_multiplier': fall_multiplier
            },
            meta={
                'detector': self.name,
                'model': 'mediapipe_pose_complexity_2',
                'architecture': 'MediaPipe Pose (33 landmarks) + shoulder-height heuristic',
                'fall_method': 'shoulder_y_threshold',
                'fall_multiplier': fall_multiplier,
                'check_interval_sec': check_interval,
                'min_detection_confidence': 0.7,
                'device': 'cpu',
                'framework': 'mediapipe'
            }
        )

    def cleanup(self) -> None:
        if hasattr(self, '_pose') and self._pose is not None:
            self._pose.close()
            self._pose = None
