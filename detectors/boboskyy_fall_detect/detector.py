import time

import cv2
import numpy as np
import mediapipe as mp
import tensorflow as tf

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


def normalize_landmarks(landmarks_frame):
    '''
    Normalize a single frame of MediaPipe landmarks.
    Extracted from notebook cell 14/20/24 normalize_landmarks().

    - Translates so hip center = origin
    - Scales xyz by torso length (hip center to shoulder center)
    - Preserves visibility channel (index 3) unchanged

    Args:
        landmarks_frame: numpy array (132,) — 33 landmarks x 4 (x, y, z, visibility)

    Returns:
        Normalized array (132,)
    '''
    reshaped = landmarks_frame.reshape(-1, 4)

    hip_center = (reshaped[23][:3] + reshaped[24][:3]) / 2.0
    shoulder_center = (reshaped[11][:3] + reshaped[12][:3]) / 2.0

    torso_size = np.linalg.norm(shoulder_center - hip_center)
    if torso_size < 0.001:
        torso_size = 1.0

    normalized = reshaped.copy()
    normalized[:, :3] -= hip_center
    normalized[:, :3] /= torso_size

    return normalized.flatten()


class BoboskyyFallDetector(BaseDetector):
    '''
    Fall detection using MediaPipe 33-point pose estimation with LSTM
    temporal classification. Trained on UR Fall Detection Dataset.

    Pipeline: MediaPipe Pose (33 landmarks, 132 features per frame)
    -> hip-center normalization + torso scaling -> 30-frame sliding
    window -> 2-layer LSTM binary classifier -> softmax threshold.

    Single person only (MediaPipe Pose limitation).
    '''

    @property
    def name(self) -> str:
        return 'boboskyy_fall_detect'

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
        '''Load Keras LSTM model. MediaPipe Pose is created fresh per request.'''
        model_path = self.config.get('model_path', '/app/models/best_model.keras')
        self._model = tf.keras.models.load_model(model_path)

        self._window_size = self.config.get('window_size', 30)
        self._threshold = self.config.get('threshold', 0.7)
        self._model_complexity = self.config.get('model_complexity', 1)
        self._min_detection_confidence = self.config.get('min_detection_confidence', 0.5)
        self._min_tracking_confidence = self.config.get('min_tracking_confidence', 0.5)

        self._initialized = True

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        '''Process video with MediaPipe pose + LSTM sliding window classification.'''
        start_time = time.time()

        cfg = request.config or {}
        threshold = cfg.get('threshold', self._threshold)
        window_size = cfg.get('window_size', self._window_size)
        frame_skip = max(cfg.get('frame_skip', 1), 1)
        model_complexity = cfg.get('model_complexity', self._model_complexity)
        min_det_conf = cfg.get('min_detection_confidence', self._min_detection_confidence)
        min_track_conf = cfg.get('min_tracking_confidence', self._min_tracking_confidence)

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise ValueError(f'Failed to open video: {request.input_path}')

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            img_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            img_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            frame_results = []
            frames_buffer = []
            frame_idx = 0

            mp_pose = mp.solutions.pose

            with mp_pose.Pose(
                min_detection_confidence=min_det_conf,
                min_tracking_confidence=min_track_conf,
                model_complexity=model_complexity
            ) as pose:

                while True:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break

                    timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

                    if frame_skip > 1 and frame_idx % frame_skip != 0:
                        frame_idx += 1
                        continue

                    image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image_rgb.flags.writeable = False
                    results = pose.process(image_rgb)

                    raw_row = np.zeros(132)
                    raw_landmarks = None
                    has_person = False

                    if results.pose_landmarks:
                        has_person = True
                        raw_landmarks = results.pose_landmarks.landmark
                        temp_row = []
                        for lm in raw_landmarks:
                            temp_row.extend([lm.x, lm.y, lm.z, lm.visibility])
                        raw_row = np.array(temp_row)

                    if has_person and np.sum(raw_row) != 0:
                        normalized_row = normalize_landmarks(raw_row)
                    else:
                        normalized_row = raw_row

                    frames_buffer.append(normalized_row)

                    fall_prob = 0.0
                    fall_state = FallState.UNKNOWN
                    has_prediction = False

                    if len(frames_buffer) >= window_size:
                        window = np.array(frames_buffer[-window_size:])
                        window = np.expand_dims(window, axis=0)

                        pred = self._model.predict(window, verbose=0)
                        fall_prob = float(pred[0][1])
                        has_prediction = True

                        if fall_prob > threshold:
                            fall_state = FallState.FALL_DETECTED
                        else:
                            fall_state = FallState.NO_FALL

                    persons = []
                    if has_person and raw_landmarks is not None:
                        keypoints = []
                        for i, lm in enumerate(raw_landmarks):
                            keypoints.append(Keypoint(
                                name=MEDIAPIPE_LANDMARK_NAMES[i],
                                x=float(lm.x * img_width),
                                y=float(lm.y * img_height),
                                z=float(lm.z),
                                confidence=float(lm.visibility)
                            ))

                        xs = [lm.x * img_width for lm in raw_landmarks]
                        ys = [lm.y * img_height for lm in raw_landmarks]
                        bbox = BoundingBox(
                            x_min=float(min(xs)),
                            y_min=float(min(ys)),
                            x_max=float(max(xs)),
                            y_max=float(max(ys)),
                            confidence=float(np.mean(
                                [lm.visibility for lm in raw_landmarks]
                            ))
                        )

                        if fall_state == FallState.FALL_DETECTED:
                            fall_confidence = fall_prob
                        elif fall_state == FallState.NO_FALL:
                            fall_confidence = 1.0 - fall_prob
                        else:
                            fall_confidence = 0.0

                        if fall_state == FallState.FALL_DETECTED:
                            activity = 'fall'
                        elif fall_state == FallState.NO_FALL:
                            activity = 'adl'
                        else:
                            activity = None

                        persons.append(PersonDetection(
                            person_id='0',
                            bbox=bbox,
                            keypoints=keypoints,
                            fall_state=fall_state,
                            fall_confidence=fall_confidence,
                            pose_confidence=float(np.mean(
                                [lm.visibility for lm in raw_landmarks]
                            )),
                            activity_label=activity,
                            features={
                                'fall_probability': fall_prob,
                                'adl_probability': 1.0 - fall_prob,
                            } if has_prediction else {}
                        ))

                    frame_results.append(FrameResult(
                        frame_index=frame_idx,
                        timestamp_ms=timestamp_ms,
                        persons=persons,
                        fall_detected=fall_state == FallState.FALL_DETECTED,
                    ))

                    frame_idx += 1

        finally:
            cap.release()

        processing_time_ms = (time.time() - start_time) * 1000

        return self._build_response(
            task_id=request.task_id,
            input_type=request.input_type,
            frame_results=frame_results,
            total_frames=total_frames if total_frames > 0 else frame_idx,
            processed_frames=len(frame_results),
            processing_time_ms=processing_time_ms,
            config_used={
                'threshold': threshold,
                'window_size': window_size,
                'frame_skip': frame_skip,
                'model_complexity': model_complexity,
                'min_detection_confidence': min_det_conf,
                'min_tracking_confidence': min_track_conf,
            },
            meta={
                'detector': self.name,
                'model': 'lstm_mediapipe_33pt',
                'model_architecture': 'LSTM(192->24) + BatchNorm + Dense(48->2)',
                'framework': 'tensorflow_keras',
                'pose_estimator': 'mediapipe_pose',
                'device': 'cpu',
                'keypoint_format': 'mediapipe_33',
                'coordinate_space': 'pixel_absolute',
                'normalization': 'hip_center_origin_torso_scaled',
                'training_dataset': 'ur_fall_detection',
            }
        )

    def cleanup(self) -> None:
        '''Release TensorFlow model.'''
        if hasattr(self, '_model'):
            del self._model
        tf.keras.backend.clear_session()
        self._initialized = False
