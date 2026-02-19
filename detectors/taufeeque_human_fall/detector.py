import os
import sys
import time
import math
import argparse

import cv2
import numpy as np
import torch

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

import openpifpaf
from vis.processor import Processor
from vis.inv_pendulum import (
    get_kp, match_ip, get_rot_energy, get_angle_vertical, get_gf,
    get_height_bbox, get_ratio_bbox, get_ratio_derivative, is_valid
)
from vis.visual import activity_dict
from model.model import LSTMModel
from default_params import (
    DEFAULT_CONSEC_FRAMES, FEATURE_LIST, FEATURE_SCALAR,
    FRAME_FEATURES, EMA_FRAMES, EMA_BETA
)
from helpers import pop_and_add, last_ip, get_hist

COCO_KEYPOINT_NAMES = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
]


class TaufeequeHumanFallDetector(BaseDetector):
    '''
    Multi-person fall detection using OpenPifPaf pose estimation (17 COCO
    keypoints) converted to a 5-point inverted pendulum model, with 5
    physics-based features fed to an LSTM temporal classifier (7 classes)
    and a false positive detection heuristic.
    '''

    @property
    def name(self) -> str:
        return 'taufeeque_human_fall'

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
        '''Load OpenPifPaf model and LSTM classifier.'''
        parser = argparse.ArgumentParser()
        openpifpaf.network.Factory.cli(parser)
        openpifpaf.decoder.cli(parser)
        args = parser.parse_args([])

        args.checkpoint = 'shufflenetv2k16'
        args.force_complete_pose = True
        args.instance_threshold = 0.2
        args.seed_threshold = 0.5
        args.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        args.pin_memory = torch.cuda.is_available()

        openpifpaf.decoder.configure(args)
        openpifpaf.network.Factory.configure(args)

        self._args = args

        self._processor = Processor((256, 256), args)

        weights_path = os.path.join(os.path.dirname(__file__), 'repo', 'model', 'lstm_weights.sav')
        self._lstm_model = LSTMModel(h_RNN=48, h_RNN_layers=2, drop_p=0.1, num_classes=7)
        self._lstm_model.load_state_dict(torch.load(weights_path, map_location=args.device))
        self._lstm_model.to(args.device)
        self._lstm_model.eval()

        self._default_resolution = self.config.get('resolution', 0.4)
        self._default_consecutive_frames = self.config.get('consecutive_frames', DEFAULT_CONSEC_FRAMES)

        self._initialized = True

    def _extract_features_and_classify(self, ip_set, lstm_set, consecutive_frames):
        '''
        Reimplemented from algorithms.py:get_all_features().
        Computes physics features and runs LSTM classification for ALL tracked persons.
        Returns list of (prediction, fall_confidence, features_dict) per person.
        '''
        results = []

        for i, ips in enumerate(ip_set):
            last1 = None
            last2 = None
            for j in range(-2, -1 * consecutive_frames - 1, -1):
                if j >= -len(ips) and ips[j] is not None:
                    if last1 is None:
                        last1 = j
                    elif last2 is None:
                        last2 = j

            if ips[-1] is not None:
                ips[-1]['features'] = {}
                ips[-1]['features']['height_bbox'] = get_height_bbox(ips[-1])
                ips[-1]['features']['ratio_bbox'] = FEATURE_SCALAR['ratio_bbox'] * get_ratio_bbox(ips[-1])

                body_vector = ips[-1]['keypoints']['N'] - ips[-1]['keypoints']['B']
                ips[-1]['features']['angle_vertical'] = FEATURE_SCALAR['angle_vertical'] * get_angle_vertical(body_vector)
                ips[-1]['features']['log_angle'] = FEATURE_SCALAR['log_angle'] * np.log(1 + np.abs(ips[-1]['features']['angle_vertical']))

                if last1 is not None:
                    ips[-1]['features']['re'] = FEATURE_SCALAR['re'] * get_rot_energy(ips[last1], ips[-1])
                    ips[-1]['features']['ratio_derivative'] = FEATURE_SCALAR['ratio_derivative'] * get_ratio_derivative(ips[last1], ips[-1])
                    if last2 is not None:
                        ips[-1]['features']['gf'] = get_gf(ips[last2], ips[last1], ips[-1])

            xdata = []
            if ips[-1] is None:
                if last1 is None:
                    xdata = [0] * len(FEATURE_LIST)
                else:
                    for feat in FEATURE_LIST[:FRAME_FEATURES]:
                        xdata.append(ips[last1]['features'].get(feat, 0))
                    xdata += [0] * (len(FEATURE_LIST) - FRAME_FEATURES)
            else:
                for feat in FEATURE_LIST:
                    if feat in ips[-1].get('features', {}):
                        xdata.append(ips[-1]['features'][feat])
                    else:
                        xdata.append(0)

            xdata_tensor = torch.Tensor(xdata).view(-1, 1, 5).to(self._args.device)
            with torch.no_grad():
                outputs, lstm_set[i][0] = self._lstm_model(xdata_tensor, lstm_set[i][0])

            prediction = torch.max(outputs.data, 1)[1][0].item()
            confidence_raw = torch.max(outputs.data, 1)[0][0].item()

            probs = torch.softmax(outputs, dim=1)
            fall_prob = probs[0][0].item()

            if prediction in [1, 2, 3, 5]:
                lstm_set[i][3] -= 1
                lstm_set[i][3] = max(lstm_set[i][3], 0)

                if lstm_set[i][2] < EMA_FRAMES:
                    if ips[-1] is not None:
                        lstm_set[i][2] += 1
                        lstm_set[i][1] = (lstm_set[i][1] * (lstm_set[i][2] - 1) + get_height_bbox(ips[-1])) / lstm_set[i][2]
                else:
                    if ips[-1] is not None:
                        lstm_set[i][1] = (1 - EMA_BETA) * get_height_bbox(ips[-1]) + EMA_BETA * lstm_set[i][1]

            elif prediction == 0:
                if (ips[-1] is not None and lstm_set[i][1] != 0
                        and abs(ips[-1]['features'].get('angle_vertical', 0)) < math.pi / 4) or confidence_raw < 0.4:
                    prediction = 7
                else:
                    lstm_set[i][3] += 1
                    if lstm_set[i][3] < consecutive_frames // 4:
                        prediction = 7
            else:
                lstm_set[i][3] -= 1
                lstm_set[i][3] = max(lstm_set[i][3], 0)

            features = {}
            if ips[-1] is not None and 'features' in ips[-1]:
                features = {k: float(v) for k, v in ips[-1]['features'].items()
                            if isinstance(v, (int, float, np.floating))}

            results.append((prediction, fall_prob, features))

        return results

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        '''Process video frame-by-frame with OpenPifPaf + LSTM fall detection.'''
        start_time = time.time()

        cfg = request.config or {}
        resolution = cfg.get('resolution', self._default_resolution)
        consecutive_frames = cfg.get('consecutive_frames', self._default_consecutive_frames)
        frame_skip = max(cfg.get('frame_skip', 1), 1)

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise ValueError(f'Failed to open video: {request.input_path}')

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            ret, first_frame = cap.read()
            if not ret:
                raise ValueError('Cannot read first frame')

            height_orig, width_orig = first_frame.shape[:2]

            width_height = (
                int(width_orig * resolution // 16) * 16,
                int(height_orig * resolution // 16) * 16
            )
            self._processor.width_height = width_height

            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

            ip_set = []
            lstm_set = []
            num_matched = 0

            frame_results = []
            frame_idx = 0

            while True:
                ret, img = cap.read()
                if not ret:
                    break

                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

                if frame_skip > 1 and frame_idx % frame_skip != 0:
                    frame_idx += 1
                    continue

                curr_time = time.time()

                img = cv2.resize(img, (width_orig, height_orig))
                hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

                keypoint_sets_raw, bb_list, wh = self._processor.single_image(img)

                kp_frames = []
                coco_kps_map = {}

                if keypoint_sets_raw.shape[0] > 0 and bb_list:
                    anns = [get_kp(kp.tolist()) for kp in keypoint_sets_raw]
                    ubboxes = [(np.asarray([width_orig, height_orig]) * np.asarray(ann[1])).astype('int32')
                               for ann in anns]
                    lbboxes = [(np.asarray([width_orig, height_orig]) * np.asarray(ann[2])).astype('int32')
                               for ann in anns]
                    bbox_list = [(np.asarray([width_orig, height_orig]) * np.asarray(box)).astype('int32')
                                 for box in bb_list]
                    uhist_list = [get_hist(hsv_img, bbox) for bbox in ubboxes]
                    lhist_list = [get_hist(img, bbox) for bbox in lbboxes]

                    kp_frames = [
                        {
                            'keypoints': keyp[0],
                            'up_hist': uh,
                            'lo_hist': lh,
                            'time': curr_time,
                            'box': box,
                            'coco_kps': kp_raw
                        }
                        for keyp, uh, lh, box, kp_raw in zip(
                            anns, uhist_list, lhist_list, bbox_list, keypoint_sets_raw
                        )
                    ]

                num_matched, new_num, indxs_unmatched = match_ip(
                    ip_set, kp_frames, lstm_set, num_matched, consecutive_frames
                )

                person_detections = []
                fall_in_frame = False

                if ip_set:
                    classification_results = self._extract_features_and_classify(
                        ip_set, lstm_set, consecutive_frames
                    )

                    for p_idx, (prediction, fall_prob, features) in enumerate(classification_results):
                        if prediction == 0:
                            fall_state = FallState.FALL_DETECTED
                            fall_in_frame = True
                        elif prediction == 7:
                            fall_state = FallState.FALL_WARNING
                        elif prediction == 15:
                            fall_state = FallState.UNKNOWN
                        else:
                            fall_state = FallState.NO_FALL

                        activity_label = activity_dict.get(prediction + 5, 'Unknown')

                        keypoints_list = []
                        bbox = None
                        pose_confidence = None

                        last_entry = ip_set[p_idx][-1] if ip_set[p_idx][-1] is not None else None
                        if last_entry is not None:
                            if 'box' in last_entry:
                                box = last_entry['box']
                                if isinstance(box, np.ndarray) and box.shape[0] >= 2:
                                    bbox = BoundingBox(
                                        x_min=float(box[0][0]),
                                        y_min=float(box[0][1]),
                                        x_max=float(box[1][0]),
                                        y_max=float(box[1][1])
                                    )

                            if 'coco_kps' in last_entry:
                                coco_kps = last_entry['coco_kps']
                                confidences = []
                                for k in range(17):
                                    kp_x = float(coco_kps[k, 0]) * width_orig
                                    kp_y = float(coco_kps[k, 1]) * height_orig
                                    kp_conf = float(coco_kps[k, 2])
                                    confidences.append(kp_conf)
                                    keypoints_list.append(Keypoint(
                                        name=COCO_KEYPOINT_NAMES[k],
                                        x=kp_x,
                                        y=kp_y,
                                        confidence=kp_conf
                                    ))
                                pose_confidence = float(np.mean(confidences)) if confidences else None

                        person_detections.append(PersonDetection(
                            person_id=f'p{p_idx}',
                            bbox=bbox,
                            keypoints=keypoints_list,
                            fall_state=fall_state,
                            fall_confidence=fall_prob,
                            pose_confidence=pose_confidence,
                            activity_label=activity_label,
                            features=features,
                        ))

                frame_results.append(FrameResult(
                    frame_index=frame_idx,
                    timestamp_ms=timestamp_ms,
                    persons=person_detections,
                    fall_detected=fall_in_frame,
                ))

                frame_idx += 1

        finally:
            cap.release()

        processing_time_ms = (time.time() - start_time) * 1000

        effective_config = {
            'resolution': resolution,
            'consecutive_frames': consecutive_frames,
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
                'model': 'openpifpaf_shufflenetv2k16w + lstm_48h_2l_7c',
                'device': str(self._args.device),
                'keypoint_format': 'coco_17',
                'coordinate_space': 'pixel_absolute',
                'openpifpaf_checkpoint': 'shufflenetv2k16',
                'consecutive_frames': consecutive_frames,
                'resolution_scale': resolution,
                'features': FEATURE_LIST,
            }
        )

    def cleanup(self) -> None:
        '''Release model resources.'''
        if hasattr(self, '_lstm_model'):
            del self._lstm_model
        if hasattr(self, '_processor'):
            del self._processor
        self._initialized = False
