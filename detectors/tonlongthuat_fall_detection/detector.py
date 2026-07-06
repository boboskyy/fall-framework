"""Adapter for tonlongthuat Real-Time-Fall-Detection (YOLO11n multi-activity)."""

import time
import cv2
import numpy as np
from typing import List, Dict, Any
from ultralytics import YOLO

from core.base_detector import BaseDetector
from core.models import (
    DetectionRequest, DetectionResponse, DetectionStatus,
    FrameResult, PersonDetection, Keypoint, BoundingBox,
    FallState, InputType
)

CLASS_NAMES = {
    0: 'violence',
    1: 'fall',
    2: 'fire',
    3: 'sit',
    4: 'sleep',
    5: 'standing',
    6: 'violence'
}

COCO_17_KEYPOINT_NAMES = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
]


class TonlongthuatFallDetectionDetector(BaseDetector):

    @property
    def name(self) -> str:
        return 'tonlongthuat_fall_detection'

    @property
    def version(self) -> str:
        return '1.0.0'

    @property
    def supported_input_types(self) -> list:
        return [InputType.VIDEO]

    @property
    def multi_person(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False

    def initialize(self) -> None:
        weights_path = self.config.get(
            'weights_path',
            '/app/repo/ok.pt'
        )
        self._model = YOLO(weights_path)

        self._smoothing_window_sec = self.config.get('smoothing_window_sec', 10.0)
        self._fall_time_threshold_sec = self.config.get('fall_time_threshold_sec', 3.0)

        self._person_fall_times: Dict[str, float] = {}
        self._person_last_timestamp: Dict[str, float] = {}

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

        confidence_threshold = request.config.get(
            'confidence_threshold', 0.6
        ) if request.config else 0.6
        smoothing_window = request.config.get(
            'smoothing_window_sec', self._smoothing_window_sec
        ) if request.config else self._smoothing_window_sec
        fall_threshold = request.config.get(
            'fall_time_threshold_sec', self._fall_time_threshold_sec
        ) if request.config else self._fall_time_threshold_sec

        frame_results: List[FrameResult] = []
        fall_events: List[Dict[str, Any]] = []
        frame_idx = 0

        self._person_fall_times.clear()
        self._person_last_timestamp.clear()

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            timestamp_sec = timestamp_ms / 1000.0

            results = self._model(frame, verbose=False)

            persons: List[PersonDetection] = []
            current_frame_person_ids = set()

            if len(results) > 0 and results[0].boxes is not None:
                boxes = results[0].boxes

                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item())
                    conf = float(boxes.conf[i].item())

                    if cls_id == 2:
                        continue

                    if conf < confidence_threshold:
                        continue

                    activity_label = CLASS_NAMES.get(cls_id, 'unknown')

                    x1, y1, x2, y2 = boxes.xyxy[i].tolist()
                    bbox = BoundingBox(
                        x_min=float(x1),
                        y_min=float(y1),
                        x_max=float(x2),
                        y_max=float(y2),
                        confidence=conf
                    )

                    person_id = str(i)
                    current_frame_person_ids.add(person_id)

                    is_fall = (cls_id == 1)

                    if person_id not in self._person_fall_times:
                        self._person_fall_times[person_id] = 0.0
                        self._person_last_timestamp[person_id] = timestamp_sec

                    last_ts = self._person_last_timestamp[person_id]
                    time_delta = timestamp_sec - last_ts

                    if is_fall:
                        self._person_fall_times[person_id] += time_delta
                    else:
                        self._person_fall_times[person_id] = max(
                            0.0,
                            self._person_fall_times[person_id] - time_delta
                        )

                    if self._person_fall_times[person_id] > smoothing_window:
                        self._person_fall_times[person_id] = smoothing_window

                    self._person_last_timestamp[person_id] = timestamp_sec

                    accumulated_fall_time = self._person_fall_times[person_id]
                    # Wiernosc oryginalowi: oznacz upadek NATYCHMIAST gdy model widzi klase 'fall'
                    # (upstream: `if class_name == 'fall'`). Bramka 3s zaniżała sygnał i gubiła krótkie
                    # upadki (0% na URFD). Agregacje czasowa zostawiamy wspolnemu progowi frameworka
                    # (min_fall_frames) — spojnie z pozostalymi detektorami emitujacymi stan per-klatka.
                    fall_detected = is_fall

                    fall_state = FallState.FALL_DETECTED if fall_detected else FallState.NO_FALL
                    fall_confidence = conf if is_fall else 0.0

                    keypoints: List[Keypoint] = []
                    if hasattr(results[0], 'keypoints') and results[0].keypoints is not None:
                        kp_data = results[0].keypoints.data[i]
                        for kp_idx, (x, y, conf_kp) in enumerate(kp_data):
                            if kp_idx < len(COCO_17_KEYPOINT_NAMES):
                                keypoints.append(Keypoint(
                                    name=COCO_17_KEYPOINT_NAMES[kp_idx],
                                    x=float(x),
                                    y=float(y),
                                    z=0.0,
                                    confidence=float(conf_kp)
                                ))

                    person = PersonDetection(
                        person_id=person_id,
                        bbox=bbox,
                        keypoints=keypoints,
                        fall_state=fall_state,
                        fall_confidence=fall_confidence,
                        pose_confidence=conf,
                        activity_label=activity_label,
                        features={
                            'class_id': cls_id,
                            'class_name': activity_label,
                            'accumulated_fall_time': accumulated_fall_time,
                            'fall_threshold': fall_threshold,
                            'is_instant_fall': is_fall,
                            'smoothing_window': smoothing_window
                        }
                    )
                    persons.append(person)

            stale_ids = set(self._person_fall_times.keys()) - current_frame_person_ids
            for pid in stale_ids:
                del self._person_fall_times[pid]
                del self._person_last_timestamp[pid]

            fall_in_frame = any(p.fall_state == FallState.FALL_DETECTED for p in persons)

            fr = FrameResult(
                frame_index=frame_idx,
                timestamp_ms=timestamp_ms,
                persons=persons,
                fall_detected=fall_in_frame,
                raw_output={
                    'num_detections': len(persons),
                    'activities': [p.activity_label for p in persons],
                    'fall_times': {p.person_id: self._person_fall_times.get(p.person_id, 0.0) for p in persons}
                } if persons else None
            )
            frame_results.append(fr)

            if fall_in_frame:
                falling_person_ids = [
                    p.person_id for p in persons
                    if p.fall_state == FallState.FALL_DETECTED
                ]

                if (len(fall_events) == 0 or
                    not fall_events[-1].get('_ongoing', False)):
                    fall_events.append({
                        'frame_index': frame_idx,
                        'timestamp_ms': timestamp_ms,
                        'persons': falling_person_ids,
                        '_ongoing': True
                    })
                else:
                    fall_events[-1]['persons'] = list(
                        set(fall_events[-1]['persons']) | set(falling_person_ids)
                    )
            elif len(fall_events) > 0 and fall_events[-1].get('_ongoing'):
                fall_events[-1]['_ongoing'] = False

            frame_idx += 1

        cap.release()

        for evt in fall_events:
            evt.pop('_ongoing', None)

        processing_time_ms = (time.time() - start_time) * 1000
        processed_count = len(frame_results)
        fall_frame_count = sum(1 for fr in frame_results if fr.fall_detected)

        effective_config = {
            'confidence_threshold': confidence_threshold,
            'smoothing_window_sec': smoothing_window,
            'fall_time_threshold_sec': fall_threshold
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
                'confidence_threshold': confidence_threshold,
                'smoothing_window_sec': smoothing_window,
                'fall_time_threshold_sec': fall_threshold
            },
            meta={
                'detector': self.name,
                'model': 'yolo11n',
                'weights': 'ok.pt',
                'architecture': 'YOLO11n (7-class multi-activity)',
                'classes': list(CLASS_NAMES.values()),
                'num_classes': len(set(CLASS_NAMES.values())),
                'confidence_threshold': confidence_threshold,
                'temporal_smoothing': True,
                'smoothing_window_sec': smoothing_window,
                'fall_time_threshold_sec': fall_threshold,
                'device': 'cpu',
                'framework': 'ultralytics'
            }
        )

    def cleanup(self) -> None:
        if hasattr(self, '_model') and self._model is not None:
            del self._model
            self._model = None
