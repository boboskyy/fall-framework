import os
import time
import cv2
from typing import List, Dict, Any

from core.base_detector import BaseDetector
from core.models import (
    DetectionRequest,
    DetectionResponse,
    FrameResult,
    PersonDetection,
    BoundingBox,
    FallState,
    InputType
)

os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'


class NoorkhokharYolov8FallDetector(BaseDetector):
    '''
    Fall detection using custom-trained YOLOv8s object detection model.

    Model has single class 'Fall-Detected' - every detection IS a fall.
    Uses ByteTrack for multi-person tracking across frames.
    '''

    @property
    def name(self) -> str:
        return 'noorkhokhar_yolov8_fall'

    @property
    def version(self) -> str:
        return '1.0.0'

    @property
    def supported_input_types(self) -> List[InputType]:
        return [InputType.VIDEO]

    @property
    def multi_person(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False

    def initialize(self) -> None:
        '''Load YOLOv8 model with bundled fall detection weights.'''
        from ultralytics import YOLO
        import torch

        weights_path = os.path.join(os.path.dirname(__file__), 'repo', 'fall_det_1.pt')
        if not os.path.exists(weights_path):
            weights_path = '/app/repo/fall_det_1.pt'

        self._model = YOLO(weights_path)

        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._conf_threshold = self.config.get('confidence_threshold', 0.5)
        self._initialized = True

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        '''Process video frame-by-frame with YOLOv8 fall detection.'''
        start_time = time.time()

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise ValueError(f'Failed to open video: {request.input_path}')

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

            frame_results: List[FrameResult] = []
            frame_idx = 0

            self._model.predictor = None

            conf_threshold = request.config.get('confidence_threshold', self._conf_threshold) if request.config else self._conf_threshold
            frame_skip = request.config.get('frame_skip', 1) if request.config else 1

            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

                if frame_idx % frame_skip != 0:
                    frame_idx += 1
                    continue

                results = self._model.track(
                    frame,
                    persist=True,
                    conf=conf_threshold,
                    device=self._device,
                    verbose=False
                )

                result = results[0]
                boxes = result.boxes

                persons: List[PersonDetection] = []
                fall_in_frame = False

                if boxes is not None and len(boxes) > 0:
                    for i in range(len(boxes)):
                        xyxy = boxes.xyxy[i].cpu().numpy()
                        conf = float(boxes.conf[i].cpu().numpy())
                        cls_id = int(boxes.cls[i].cpu().numpy())

                        if boxes.id is not None:
                            track_id = str(int(boxes.id[i].cpu().numpy()))
                        else:
                            track_id = str(i)

                        bbox = BoundingBox(
                            x_min=float(xyxy[0]),
                            y_min=float(xyxy[1]),
                            x_max=float(xyxy[2]),
                            y_max=float(xyxy[3]),
                            confidence=conf
                        )

                        fall_state = FallState.FALL_DETECTED
                        fall_in_frame = True

                        person = PersonDetection(
                            person_id=track_id,
                            bbox=bbox,
                            keypoints=[],
                            fall_state=fall_state,
                            fall_confidence=conf,
                            pose_confidence=0.0,
                            activity_label='falling',
                            features={
                                'detection_confidence': conf,
                                'class_id': float(cls_id),
                                'class_name': 'Fall-Detected'
                            }
                        )
                        persons.append(person)

                fr = FrameResult(
                    frame_index=frame_idx,
                    timestamp_ms=timestamp_ms,
                    persons=persons,
                    fall_detected=fall_in_frame,
                    raw_output={
                        'num_detections': len(persons),
                        'confidences': [p.fall_confidence for p in persons]
                    } if persons else None
                )
                frame_results.append(fr)

                frame_idx += 1

        finally:
            cap.release()

        processing_time_ms = (time.time() - start_time) * 1000

        effective_config = {
            'confidence_threshold': conf_threshold,
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
                'model': 'yolov8s-custom-fall-detection',
                'model_weights': 'fall_det_1.pt',
                'base_architecture': 'YOLOv8s',
                'num_classes': 1,
                'class_names': {0: 'Fall-Detected'},
                'training_imgsz': 640,
                'confidence_threshold': conf_threshold,
                'tracker': 'ByteTrack',
                'device': self._device,
                'frame_skip': frame_skip,
                'fps': fps
            }
        )

    def cleanup(self) -> None:
        '''Release model resources.'''
        if hasattr(self, '_model'):
            del self._model
            self._model = None
