"""{{DISPLAY_NAME}} - Fall Detection Adapter

TODO: Implement the adapter for your fall detection model.

This file subclasses BaseDetector and wraps your model's inference logic
into the standardized framework API. The framework handles all HTTP routing,
task management, and error handling — you only implement detection logic.

Lifecycle:
    1. initialize() — called once at startup. Load your model here.
    2. detect(request) — called per request. Process input, return results.
    3. cleanup() — called at shutdown. Release resources.
"""

import cv2
import time
from typing import List

from core.base_detector import BaseDetector
from core.models import (
    InputType, FallState, DetectionRequest, DetectionResponse,
    FrameResult, PersonDetection, BoundingBox
)


class {{DETECTOR_CLASS}}(BaseDetector):
    """TODO: Add a one-line description of your detector."""

    @property
    def name(self) -> str:
        return '{{DETECTOR_NAME}}'

    @property
    def version(self) -> str:
        return '1.0.0'

    @property
    def supported_input_types(self) -> List[InputType]:
        return [InputType.VIDEO]

    @property
    def multi_person(self) -> bool:
        return False  # TODO: Set True if your model tracks multiple people

    @property
    def requires_gpu(self) -> bool:
        return False

    def initialize(self) -> None:
        """Load your model. Called once at startup by the framework.

        TODO: Replace with your actual model loading code.
        Example (PyTorch):
            import torch
            self._device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            self._model = torch.load('/app/repo/weights/model.pt', map_location=self._device)

        Example (Ultralytics YOLO):
            from ultralytics import YOLO
            self._model = YOLO('/app/repo/weights/model.pt')
            # Ultralytics auto-detects GPU

        Example (TensorFlow):
            import tensorflow as tf
            self._model = tf.keras.models.load_model('/app/repo/weights/model.h5')
            # TensorFlow auto-detects GPU
        """
        # TODO: Load your model here
        # self._model = ...
        self._conf_threshold = self.config.get('confidence_threshold', 0.5)

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        """Process a video file and return fall detection results.

        TODO: Replace the frame loop with your actual detection logic.

        Args:
            request: DetectionRequest with input_path, config, task_id, etc.

        Returns:
            DetectionResponse via self._build_response()
        """
        effective_config = {
            'confidence_threshold': self._conf_threshold,
        }
        if request.config:
            effective_config.update(request.config)

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise RuntimeError(f'Cannot open video: {request.input_path}')

        frame_results = []
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_skip = int(effective_config.get('frame_skip', 1))
        start_time = time.time()

        try:
            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

                if frame_idx % frame_skip != 0:
                    frame_idx += 1
                    continue

                # -----------------------------------------------------------
                # TODO: Replace this block with your model's inference logic.
                #
                # Your model should produce per-frame results. For each frame:
                #   1. Run your model on the frame
                #   2. Extract person detections (bounding boxes, keypoints, etc.)
                #   3. Determine fall state for each person
                #   4. Build PersonDetection objects
                #   5. Build a FrameResult
                #
                # Example (YOLO-based):
                #   results = self._model(frame)
                #   for box in results[0].boxes:
                #       if box.cls == FALL_CLASS:
                #           persons.append(PersonDetection(...))
                #
                # Example (pose-based):
                #   keypoints = self._pose_model.process(frame)
                #   fall = self._check_fall_rules(keypoints)
                #   persons.append(PersonDetection(fall_state=...))
                # -----------------------------------------------------------

                persons = []
                fall_detected = False  # TODO: Set from your model output

                # TODO: Build PersonDetection for each detected person
                # persons.append(PersonDetection(
                #     person_id='p0',
                #     bbox=BoundingBox(x_min=..., y_min=..., x_max=..., y_max=...,
                #                      confidence=...),
                #     fall_state=FallState.FALL_DETECTED if fall else FallState.NO_FALL,
                #     fall_confidence=confidence,
                # ))
                # fall_detected = any(p.fall_state == FallState.FALL_DETECTED for p in persons)

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

        return self._build_response(
            task_id=request.task_id,
            input_type=request.input_type,
            frame_results=frame_results,
            total_frames=total_frames,
            processed_frames=len(frame_results),
            processing_time_ms=processing_time_ms,
            config_used=effective_config,
        )

    def cleanup(self) -> None:
        """Release model resources."""
        if hasattr(self, '_model'):
            del self._model
