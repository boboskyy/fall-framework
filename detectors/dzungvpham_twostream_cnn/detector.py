"""Adapter for dzungvpham fall-detection-two-stream-cnn detector."""

import os
import time
import math
import cv2 as cv
import numpy as np
from typing import List, Dict, Any

from core.base_detector import BaseDetector
from core.models import (
    DetectionRequest, DetectionResponse, DetectionStatus,
    FrameResult, PersonDetection, BoundingBox,
    FallState, InputType
)

IMAGE_SIZE = 224
MHI_DURATION = 1500
MHI_DURATION_SHORT = 300
THRESHOLD = 32
GAUSSIAN_KERNEL = (3, 3)


def _build_model(weights_path):
    """
    Recreate the two-stream model using TF2-compatible Keras imports.
    Mirrors train_model.py:19-66 but uses tensorflow.keras.
    """
    from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2
    from tensorflow.keras.models import Model
    from tensorflow.keras.layers import (
        Dense, BatchNormalization, Activation, Dropout,
        GlobalAveragePooling2D, Concatenate
    )

    def _create_base_model(prefix, image_size=224):
        base_model = MobileNetV2(
            input_shape=(image_size, image_size, 3),
            alpha=1.0,
            include_top=False, weights='imagenet'
        )
        if prefix is not None:
            for layer in base_model.layers:
                layer._name = prefix + '_' + layer.name
        for layer in base_model.layers:
            layer.trainable = False

        out = base_model.output
        out = GlobalAveragePooling2D()(out)
        out = Dense(256)(out)
        out = BatchNormalization()(out)
        out = Activation('relu')(out)
        out = Dropout(0.5)(out)
        return base_model, out

    spatial_stream, spatial_output = _create_base_model(prefix='spatial')
    temporal_stream, temporal_output = _create_base_model(prefix='temporal')
    out = Concatenate()([spatial_output, temporal_output])

    out = Dense(128)(out)
    out = BatchNormalization()(out)
    out = Activation('relu')(out)
    out = Dropout(0.5)(out)

    out = Dense(128)(out)
    out = BatchNormalization()(out)
    out = Activation('relu')(out)
    out = Dropout(0.5)(out)

    predictions = Dense(1, activation='sigmoid')(out)
    model = Model(
        inputs=[spatial_stream.input, temporal_stream.input],
        outputs=predictions
    )

    model.load_weights(weights_path)
    return model


class DzungvphamTwoStreamCnnDetector(BaseDetector):

    @property
    def name(self) -> str:
        return 'dzungvpham_twostream_cnn'

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
        weights_path = os.path.join(
            os.path.dirname(__file__), 'repo', 'weights', 'weights.hdf5'
        )
        if not os.path.exists(weights_path):
            weights_path = '/app/repo/weights/weights.hdf5'

        self._model = _build_model(weights_path)
        self._conf_threshold = self.config.get('confidence_threshold', 0.5)
        self._initialized = True

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

        start_time = time.time()

        cap = cv.VideoCapture(request.input_path)
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

        total_frames = int(cap.get(cv.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0
        fps_int = int(fps)
        cap_width = cap.get(cv.CAP_PROP_FRAME_WIDTH)
        cap_height = cap.get(cv.CAP_PROP_FRAME_HEIGHT)

        conf_threshold = request.config.get(
            'confidence_threshold', self._conf_threshold
        ) if request.config else self._conf_threshold

        interval = int(max(1,
            math.ceil(fps_int / 10)
            if (fps_int / 10 - math.floor(fps_int / 10)) >= 0.5
            else math.floor(fps_int / 10)
        ))
        ms_per_frame = 1000.0 / fps

        prev_mhi = [np.zeros((IMAGE_SIZE, IMAGE_SIZE), np.float32) for _ in range(interval)]
        prev_mhi_short = [np.zeros((IMAGE_SIZE, IMAGE_SIZE), np.float32) for _ in range(interval)]
        prev_timestamp = [i * ms_per_frame for i in range(interval)]
        prev_frames = [None] * interval

        for i in range(interval):
            ret, frame = cap.read()
            if not ret:
                break
            frame = cv.resize(frame, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv.INTER_AREA)
            frame = cv.GaussianBlur(frame, GAUSSIAN_KERNEL, 0)
            prev_frames[i] = frame.copy()

        fall_frames_seen = 0
        fall_detected = False
        MIN_NUM_FALL_FRAME = max(1, int(fps_int / 5))

        frame_results: List[FrameResult] = []
        fall_events: List[Dict[str, Any]] = []
        count = interval
        frame_idx = interval

        while cap.isOpened():
            ret, orig_frame = cap.read()
            if not ret:
                break

            timestamp_ms = cap.get(cv.CAP_PROP_POS_MSEC)

            prev_ind = count % interval
            prev_timestamp[prev_ind] += interval * ms_per_frame
            count += 1

            frame = cv.resize(orig_frame, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv.INTER_AREA)
            frame = cv.GaussianBlur(frame, GAUSSIAN_KERNEL, 0)

            if prev_frames[prev_ind] is not None:
                frame_diff = cv.absdiff(frame, prev_frames[prev_ind])
            else:
                frame_diff = np.zeros_like(frame)

            gray_diff = cv.cvtColor(frame_diff, cv.COLOR_BGR2GRAY)
            _, motion_mask = cv.threshold(gray_diff, THRESHOLD, 1, cv.THRESH_BINARY)
            prev_frames[prev_ind] = frame.copy()

            cv.motempl.updateMotionHistory(
                motion_mask, prev_mhi[prev_ind],
                prev_timestamp[prev_ind], MHI_DURATION
            )
            cv.motempl.updateMotionHistory(
                motion_mask, prev_mhi_short[prev_ind],
                prev_timestamp[prev_ind], MHI_DURATION_SHORT
            )
            mhi = np.uint8(np.clip(
                (prev_mhi[prev_ind] - (prev_timestamp[prev_ind] - MHI_DURATION)) / MHI_DURATION,
                0, 1
            ) * 255)
            mhi_short = np.uint8(np.clip(
                (prev_mhi_short[prev_ind] - (prev_timestamp[prev_ind] - MHI_DURATION_SHORT)) / MHI_DURATION_SHORT,
                0, 1
            ) * 255)

            x_start = y_start = IMAGE_SIZE
            x_end = y_end = 0
            contours, _ = cv.findContours(mhi_short, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
            if len(contours) > 0:
                for c in contours:
                    contour = cv.approxPolyDP(c, 3, True)
                    x, y, w, h = cv.boundingRect(contour)
                    if x < x_start:
                        x_start = x
                    if y < y_start:
                        y_start = y
                    if x + w > x_end:
                        x_end = x + w
                    if y + h > y_end:
                        y_end = y + h
            else:
                x_start = y_start = 0
                x_end = y_end = IMAGE_SIZE

            bbox_x_start = int(np.round(x_start / IMAGE_SIZE * cap_width))
            bbox_y_start = int(np.round(y_start / IMAGE_SIZE * cap_height))
            bbox_x_end = int(np.round(x_end / IMAGE_SIZE * cap_width))
            bbox_y_end = int(np.round(y_end / IMAGE_SIZE * cap_height))

            cropped = orig_frame[bbox_y_start:bbox_y_end, bbox_x_start:bbox_x_end].copy()
            try:
                cropped = cv.resize(cropped, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv.INTER_LINEAR)
            except Exception:
                cropped = cv.resize(orig_frame, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv.INTER_LINEAR)

            spatial_input = cv.cvtColor(cropped, cv.COLOR_BGR2RGB).astype(np.float32)
            spatial_input = np.expand_dims(spatial_input, axis=0)
            temporal_input = cv.cvtColor(mhi, cv.COLOR_GRAY2RGB).astype(np.float32)
            temporal_input = np.expand_dims(temporal_input, axis=0)
            preprocess_input(spatial_input)
            preprocess_input(temporal_input)

            raw_prediction = self._model.predict(
                [spatial_input, temporal_input], verbose=0
            )
            raw_confidence = float(raw_prediction[0][0])
            is_fall_frame = raw_confidence >= conf_threshold

            if is_fall_frame:
                fall_frames_seen = min(fall_frames_seen + 1, MIN_NUM_FALL_FRAME)
            else:
                fall_frames_seen = max(fall_frames_seen - 1, 0)

            if fall_frames_seen >= MIN_NUM_FALL_FRAME:
                fall_detected = True
            elif fall_frames_seen == 0:
                fall_detected = False

            fall_state = FallState.FALL_DETECTED if fall_detected else FallState.NO_FALL
            bbox = BoundingBox(
                x_min=float(bbox_x_start),
                y_min=float(bbox_y_start),
                x_max=float(bbox_x_end),
                y_max=float(bbox_y_end),
                confidence=raw_confidence
            )

            persons = [
                PersonDetection(
                    person_id='0',
                    bbox=bbox,
                    keypoints=[],
                    fall_state=fall_state,
                    fall_confidence=raw_confidence,
                    pose_confidence=0.0,
                    activity_label='falling' if fall_detected else 'not_falling',
                    features={
                        'raw_sigmoid': raw_confidence,
                        'is_fall_raw': float(is_fall_frame),
                        'fall_frames_seen': float(fall_frames_seen),
                        'min_num_fall_frame': float(MIN_NUM_FALL_FRAME),
                        'fall_detected_smoothed': float(fall_detected),
                    }
                )
            ]

            fr = FrameResult(
                frame_index=frame_idx,
                timestamp_ms=timestamp_ms,
                persons=persons,
                fall_detected=fall_detected,
                raw_output={
                    'raw_sigmoid': raw_confidence,
                    'is_fall_raw': is_fall_frame,
                    'fall_detected_smoothed': fall_detected,
                    'fall_frames_seen': fall_frames_seen,
                    'motion_bbox_224': [x_start, y_start, x_end, y_end],
                    'motion_bbox_orig': [bbox_x_start, bbox_y_start, bbox_x_end, bbox_y_end]
                }
            )
            frame_results.append(fr)

            if fall_detected and (
                len(fall_events) == 0 or
                fall_events[-1]['frame_index'] != frame_idx - 1
            ):
                fall_events.append({
                    'frame_index': frame_idx,
                    'timestamp_ms': timestamp_ms,
                    'persons': ['0']
                })

            frame_idx += 1

        cap.release()
        processing_time_ms = (time.time() - start_time) * 1000

        processed_count = len(frame_results)
        fall_frame_count = sum(1 for fr in frame_results if fr.fall_detected)

        effective_config = {
            'confidence_threshold': conf_threshold,
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
                'mhi_duration_ms': MHI_DURATION,
                'temporal_smoothing_window': MIN_NUM_FALL_FRAME
            },
            meta={
                'detector': self.name,
                'model': 'two_stream_cnn_mobilenetv2_mhi',
                'model_weights': 'weights/weights.hdf5',
                'architecture': 'Two-stream MobileNetV2 (spatial RGB + temporal MHI)',
                'input_size': IMAGE_SIZE,
                'mhi_duration_ms': MHI_DURATION,
                'threshold': THRESHOLD,
                'confidence_threshold': conf_threshold,
                'device': 'cpu',
                'framework': 'tensorflow/keras'
            }
        )

    def cleanup(self) -> None:
        if hasattr(self, '_model') and self._model is not None:
            del self._model
            self._model = None
