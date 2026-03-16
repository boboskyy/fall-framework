import os
import sys
import time

import cv2

from core.base_detector import BaseDetector
from core.models import (
    DetectionRequest,
    DetectionResponse,
    FrameResult,
    PersonDetection,
    Keypoint,
    BoundingBox,
    FallState,
    InputType
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'repo'))

COCO_KEYPOINTS = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
]


class YbClassFallDetector(BaseDetector):
    '''
    Multi-person fall detection using YOLOv7-w6-pose keypoint estimation
    with rule-based biomechanical analysis (velocity, vertical displacement,
    aspect-ratio change over a sliding window).
    '''

    @property
    def name(self) -> str:
        return 'yb_class_fall'

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
        '''Load YOLOv7-w6-pose model and create fall detector.'''
        from fall_core import FallDetectorMulti

        weights_path = os.path.join(os.path.dirname(__file__), 'repo', 'yolov7-w6-pose.pt')
        if not os.path.exists(weights_path):
            weights_path = '/app/yolov7-w6-pose.pt'

        self._default_window_size = self.config.get('window_size', 30)
        self._default_v_thresh = self.config.get('v_thresh', 60.0)
        self._default_ar_thresh = self.config.get('ar_thresh', 0.35)
        self._default_dy_thresh = self.config.get('dy_thresh', 20.0)

        self._detector = FallDetectorMulti(
            model_path=weights_path,
            window_size=self._default_window_size,
            fps=self.config.get('fps', 30),
            v_thresh=self._default_v_thresh,
            ar_thresh=self._default_ar_thresh,
            dy_thresh=self._default_dy_thresh,
        )
        self._initialized = True

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        '''Process video frame-by-frame with YOLOv7-pose + rule-based fall detection.'''
        from fall_core import PersonFallTracker

        start_time = time.time()

        self._detector.trackers = {}
        self._detector.next_id = 1

        cfg = request.config or {}
        v_thresh = cfg.get('v_thresh', self._default_v_thresh)
        dy_thresh = cfg.get('dy_thresh', self._default_dy_thresh)
        ar_thresh = cfg.get('ar_thresh', self._default_ar_thresh)
        window_size = max(cfg.get('window_size', self._default_window_size), 2)
        frame_skip = cfg.get('frame_skip', 1)

        self._detector.v_thresh = v_thresh
        self._detector.dy_thresh = dy_thresh
        self._detector.ar_thresh = ar_thresh
        self._detector.window_size = window_size

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise ValueError(f'Failed to open video: {request.input_path}')

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

            self._detector.fps = video_fps / frame_skip

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

                people, _ = self._detector.get_pose(frame)

                assigned_ids = set()
                persons = []
                fall_in_frame = False

                for pose in people:
                    tid = self._detector.match_pose_to_tracker(
                        pose, self._detector.trackers, assigned_ids,
                        timeout=float('inf')
                    )
                    if tid is None:
                        tid = str(self._detector.next_id)
                        self._detector.next_id += 1
                        self._detector.trackers[tid] = PersonFallTracker(
                            self._detector.window_size,
                            self._detector.fps,
                            self._detector.v_thresh,
                            self._detector.ar_thresh,
                            self._detector.dy_thresh,
                        )
                    self._detector.trackers[tid].add_pose(pose)
                    self._detector.trackers[tid].last_update = time.time()

                    keypoints = []
                    for k in range(17):
                        kpt_idx = 7 + k * 3
                        if kpt_idx + 2 < len(pose):
                            keypoints.append(Keypoint(
                                name=COCO_KEYPOINTS[k],
                                x=float(pose[kpt_idx]),
                                y=float(pose[kpt_idx + 1]),
                                confidence=float(pose[kpt_idx + 2])
                            ))

                    cx, cy, w, h = float(pose[2]), float(pose[3]), float(pose[4]), float(pose[5])
                    bbox = BoundingBox(
                        x_min=cx - w / 2,
                        y_min=cy - h / 2,
                        x_max=cx + w / 2,
                        y_max=cy + h / 2,
                        confidence=float(pose[6])
                    )

                    fall_state = FallState.UNKNOWN
                    fall_confidence = 0.0
                    features = {}
                    activity_label = None

                    tracker = self._detector.trackers[tid]
                    if tracker.is_ready():
                        is_fall, _, _, tag = tracker.check_fall()
                        p1 = tracker.pose_window[0]
                        p2 = tracker.pose_window[-1]
                        v, dy = tracker.compute_velocity(p1, p2)
                        ar_delta = tracker.compute_ar_delta(p1, p2)

                        features = {
                            'velocity': float(v) if v is not None else 0.0,
                            'dy': float(dy) if dy is not None else 0.0,
                            'ar_delta': float(ar_delta) if ar_delta is not None else 0.0,
                            'tag': tag if tag else '',
                        }

                        if is_fall:
                            fall_state = FallState.FALL_DETECTED
                            fall_confidence = min(1.0, v / (self._detector.v_thresh * 2)) if v else 0.7
                            fall_in_frame = True
                            activity_label = 'falling'
                        else:
                            fall_state = FallState.NO_FALL
                            fall_confidence = 0.0
                            activity_label = 'not_falling'

                    persons.append(PersonDetection(
                        person_id=tid,
                        bbox=bbox,
                        keypoints=keypoints,
                        fall_state=fall_state,
                        fall_confidence=fall_confidence,
                        pose_confidence=float(pose[6]),
                        activity_label=activity_label,
                        features=features,
                    ))

                frame_results.append(FrameResult(
                    frame_index=frame_idx,
                    timestamp_ms=timestamp_ms,
                    persons=persons,
                    fall_detected=fall_in_frame,
                ))

                frame_idx += 1

        finally:
            cap.release()

        processing_time_ms = (time.time() - start_time) * 1000

        effective_config = {
            'v_thresh': v_thresh,
            'dy_thresh': dy_thresh,
            'ar_thresh': ar_thresh,
            'window_size': window_size,
            'frame_skip': frame_skip
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
                'model': 'yolov7-w6-pose',
                'device': str(self._detector.device),
                'keypoint_format': 'coco_17',
                'coordinate_space': 'letterboxed_960',
                'detection_thresholds': {
                    'v_thresh': self._detector.v_thresh,
                    'dy_thresh': self._detector.dy_thresh,
                    'ar_thresh': self._detector.ar_thresh,
                    'window_size': self._detector.window_size,
                },
                'video_fps': video_fps,
            }
        )

    def cleanup(self) -> None:
        '''Release model resources.'''
        if hasattr(self, '_detector') and self._detector is not None:
            if hasattr(self._detector, 'model'):
                del self._detector.model
            self._detector = None
