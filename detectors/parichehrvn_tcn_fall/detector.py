import os
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from collections import deque

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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'repo', 'fall_detection', 'models'))
from tcn import TemporalConvNet

COCO_KEYPOINTS = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
]


class ParichehrvnTcnFallDetector(BaseDetector):
    '''
    Fall detection using YOLOv11-Pose for 17-keypoint extraction and a
    Temporal Convolutional Network (TCN) on 15-frame sliding windows for
    temporal classification (ADL vs Fall).
    '''

    @property
    def name(self) -> str:
        return 'parichehrvn_tcn_fall'

    @property
    def version(self) -> str:
        return '1.0.0'

    @property
    def supported_input_types(self):
        return [InputType.VIDEO]

    @property
    def multi_person(self) -> bool:
        return False

    @property
    def requires_gpu(self) -> bool:
        return False

    def initialize(self) -> None:
        '''Load YOLOv11-Pose and TCN models.'''
        from ultralytics import YOLO

        self._device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        pose_path = os.path.join(
            os.path.dirname(__file__), 'repo', 'cfg', 'models', 'pose', 'best_yolov11_pose.pt'
        )
        if not os.path.exists(pose_path):
            pose_path = '/app/repo/cfg/models/pose/best_yolov11_pose.pt'
        self._pose_model = YOLO(pose_path)

        tcn_path = os.path.join(
            os.path.dirname(__file__), 'repo', 'cfg', 'models', 'tcn', 'best_tcn.pt'
        )
        if not os.path.exists(tcn_path):
            tcn_path = '/app/repo/cfg/models/tcn/best_tcn.pt'

        self._tcn_model = TemporalConvNet(
            num_inputs=34,
            num_channels=[64, 128, 256]
        )
        self._tcn_model.load_state_dict(
            torch.load(tcn_path, map_location=self._device)
        )
        self._tcn_model.to(self._device)
        self._tcn_model.eval()

        self._default_seq_len = self.config.get('seq_len', 15)
        self._default_confidence_threshold = self.config.get('confidence_threshold', 0.5)

        self._initialized = True

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        '''Process video with YOLOv11-Pose + TCN sliding window.'''
        start_time = time.time()

        cfg = request.config or {}
        seq_len = cfg.get('seq_len', self._default_seq_len)
        confidence_threshold = cfg.get('confidence_threshold', self._default_confidence_threshold)
        frame_skip = cfg.get('frame_skip', 1)

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise ValueError(f'Failed to open video: {request.input_path}')

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

            keypoints_window = deque(maxlen=seq_len)
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

                results = self._pose_model(frame, verbose=False)[0]

                bbox = None
                keypoints = []
                xyn_array = np.zeros((17, 2))
                kpt_confs = np.zeros(17)
                pose_confidence = 0.0
                person_detected = False

                if results.boxes is not None and len(results.boxes) > 0:
                    box = results.boxes[0]
                    xyxy = box.xyxy[0].cpu().numpy()
                    bbox = BoundingBox(
                        x_min=float(xyxy[0]),
                        y_min=float(xyxy[1]),
                        x_max=float(xyxy[2]),
                        y_max=float(xyxy[3]),
                        confidence=float(box.conf[0].cpu())
                    )
                    pose_confidence = float(box.conf[0].cpu())

                    if results.keypoints is not None:
                        xyn = results.keypoints.xyn[0]
                        if hasattr(xyn, 'cpu'):
                            xyn = xyn.cpu().numpy()
                        else:
                            xyn = np.array(xyn)

                        if xyn.shape[0] == 17:
                            xyn_array = xyn
                            person_detected = True

                            if results.keypoints.conf is not None:
                                conf = results.keypoints.conf[0]
                                if hasattr(conf, 'cpu'):
                                    kpt_confs = conf.cpu().numpy()
                                else:
                                    kpt_confs = np.array(conf)

                for k in range(17):
                    keypoints.append(Keypoint(
                        name=COCO_KEYPOINTS[k],
                        x=float(xyn_array[k][0]),
                        y=float(xyn_array[k][1]),
                        confidence=float(kpt_confs[k])
                    ))

                keypoints_window.append(xyn_array)

                fall_state = FallState.UNKNOWN
                fall_confidence = 0.0
                activity_label = None

                if len(keypoints_window) == seq_len:
                    kp_array = np.array(keypoints_window)
                    kp_tensor = torch.tensor(kp_array, dtype=torch.float32)
                    kp_tensor = kp_tensor.reshape(seq_len, -1).permute(1, 0).unsqueeze(0)
                    kp_tensor = kp_tensor.to(self._device)

                    with torch.no_grad():
                        outputs = self._tcn_model(kp_tensor)
                        probs = F.softmax(outputs, dim=1)
                        predicted_label = torch.argmax(outputs, dim=1).item()
                        fall_confidence = float(probs[0, 1].cpu())

                    if predicted_label == 1 and fall_confidence >= confidence_threshold:
                        fall_state = FallState.FALL_DETECTED
                        activity_label = 'falling'
                    elif predicted_label == 1 and fall_confidence < confidence_threshold:
                        fall_state = FallState.FALL_WARNING
                        activity_label = 'falling'
                    else:
                        fall_state = FallState.NO_FALL
                        activity_label = 'not_falling'

                person = PersonDetection(
                    person_id='1',
                    bbox=bbox,
                    keypoints=keypoints,
                    fall_state=fall_state,
                    fall_confidence=fall_confidence,
                    pose_confidence=pose_confidence if person_detected else None,
                    activity_label=activity_label,
                )

                fall_in_frame = fall_state == FallState.FALL_DETECTED

                frame_results.append(FrameResult(
                    frame_index=frame_idx,
                    timestamp_ms=timestamp_ms,
                    persons=[person] if person_detected or len(keypoints_window) == seq_len else [],
                    fall_detected=fall_in_frame,
                ))

                frame_idx += 1

        finally:
            cap.release()

        processing_time_ms = (time.time() - start_time) * 1000

        effective_config = {
            'seq_len': seq_len,
            'confidence_threshold': confidence_threshold,
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
                'models': ['yolov11-pose', 'tcn'],
                'device': str(self._device),
                'keypoint_format': 'coco_17',
                'coordinate_space': 'normalized',
                'video_fps': video_fps,
                'tcn_architecture': {
                    'num_inputs': 34,
                    'num_channels': [64, 128, 256],
                    'seq_len': seq_len,
                },
            }
        )

    def cleanup(self) -> None:
        '''Release model resources.'''
        if hasattr(self, '_pose_model'):
            del self._pose_model
            self._pose_model = None
        if hasattr(self, '_tcn_model'):
            del self._tcn_model
            self._tcn_model = None
