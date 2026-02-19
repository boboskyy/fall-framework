import os
import sys
import time
import math
import argparse

import cv2
import numpy as np
import torch
import PIL.Image

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

from openpifpaf.network import factory as net_factory, configure as net_configure, cli as net_cli
from openpifpaf.decoder import factory_from_args as dec_factory_from_args, cli as dec_cli
from openpifpaf.visualizer import cli as vis_cli, configure as vis_configure
from openpifpaf import transforms
from openpifpaf.core.tracker import CentroidTracker
from openpifpaf.core.falldetector import FallDetector as RepoFallDetector

COCO_KEYPOINT_NAMES = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
]


class CwlrodaOpenpifpafDetector(BaseDetector):
    '''
    Multi-person fall detection using OpenPifPaf 0.11.8 pose estimation
    (17 COCO keypoints) with Euclidean centroid tracking and rule-based
    fall classification: bbox aspect ratio (w >= 1.2*h) + centroid
    displacement (>= 0.5 * bbox diagonal).
    '''

    @property
    def name(self) -> str:
        return 'cwlroda_openpifpaf'

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
        '''Load OpenPifPaf model and create decoder/processor.'''
        parser = argparse.ArgumentParser()
        net_cli(parser)
        dec_cli(parser)
        vis_cli(parser)
        args = parser.parse_args([])

        args.debug = False
        args.debug_images = False
        args.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        args.checkpoint = 'shufflenetv2k16w'

        net_configure(args)
        vis_configure(args)

        model_cpu, _ = net_factory(checkpoint=args.checkpoint)
        self._model = model_cpu.to(args.device)
        self._model.eval()

        self._processor = dec_factory_from_args(args, self._model)

        self._device = args.device
        self._scale = self.config.get('scale', 1.0)

        self._initialized = True

    def _extract_centroid(self, ann):
        '''
        Extract shoulder midpoint centroid from annotation.
        Replicates show/painters.py:178-203 _draw_skeleton() logic.
        Returns (mid_x, mid_y, x_, y_, w_, h_) or None.
        '''
        kps = ann.data
        x = kps[:, 0]
        y = kps[:, 1]
        v = kps[:, 2]

        if not np.any(v > 0):
            return None

        lx, rx = x[5], x[6]
        ly, ry = y[5], y[6]

        if lx != 0 and rx == 0:
            mid_x = lx
        elif lx == 0 and rx != 0:
            mid_x = rx
        elif lx != 0 and rx != 0:
            mid_x = (lx + rx) / 2
        else:
            return None

        if ly != 0 and ry == 0:
            mid_y = ly
        elif ly == 0 and ry != 0:
            mid_y = ry
        elif ly != 0 and ry != 0:
            mid_y = (ly + ry) / 2
        else:
            return None

        bbox = ann.bbox()
        x_, y_, w_, h_ = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])

        if w_ < 5.0:
            x_ -= 2.0
            w_ += 4.0
        if h_ < 5.0:
            y_ -= 2.0
            h_ += 4.0

        return (mid_x, mid_y, x_, y_, w_, h_)

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        '''Process video with OpenPifPaf pose estimation and rule-based fall detection.'''
        start_time = time.time()

        cfg = request.config or {}
        scale = cfg.get('scale', self._scale)
        frame_skip = max(cfg.get('frame_skip', 1), 1)

        cap = cv2.VideoCapture(request.input_path)
        if not cap.isOpened():
            raise ValueError(f'Failed to open video: {request.input_path}')

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            ct = CentroidTracker()
            fd = RepoFallDetector()
            framecount = 0

            frame_results = []
            frame_idx = 0

            while True:
                ret, image = cap.read()
                if not ret or image is None:
                    break

                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

                if frame_skip > 1 and frame_idx % frame_skip != 0:
                    frame_idx += 1
                    continue

                if scale != 1.0:
                    image = cv2.resize(image, None, fx=scale, fy=scale)

                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                image_pil = PIL.Image.fromarray(image_rgb)

                processed_image, _, __ = transforms.EVAL_TRANSFORM(image_pil, [], None)

                with torch.no_grad():
                    preds = self._processor.batch(
                        self._model,
                        torch.unsqueeze(processed_image, 0),
                        device=self._device
                    )[0]

                centroids = []
                ann_map = []
                for ann in preds:
                    centroid = self._extract_centroid(ann)
                    if centroid is not None:
                        centroids.append(centroid)
                        ann_map.append((centroid, ann))

                persons = ct.update(centroids, fps)

                falls = fd.update(persons, framecount, fps)

                person_detections = []
                fall_in_frame = len(falls) > 0

                for pid, centroid_data in persons.items():
                    px = float(centroid_data[0])
                    py = float(centroid_data[1])
                    px_ = float(centroid_data[2])
                    py_ = float(centroid_data[3])
                    pw_ = float(centroid_data[4])
                    ph_ = float(centroid_data[5])

                    is_falling = pid in falls

                    best_ann = None
                    best_dist = float('inf')
                    for (cx, cy, *_rest), ann in ann_map:
                        d = math.sqrt((cx - px) ** 2 + (cy - py) ** 2)
                        if d < best_dist:
                            best_dist = d
                            best_ann = ann

                    keypoints_list = []
                    pose_conf = 0.0
                    bbox = BoundingBox(
                        x_min=px_,
                        y_min=py_,
                        x_max=px_ + pw_,
                        y_max=py_ + ph_
                    )

                    if best_ann is not None:
                        kps = best_ann.data
                        for j in range(17):
                            keypoints_list.append(Keypoint(
                                name=COCO_KEYPOINT_NAMES[j],
                                x=float(kps[j, 0]),
                                y=float(kps[j, 1]),
                                confidence=float(kps[j, 2])
                            ))
                        pose_conf = float(best_ann.score())

                        ab = best_ann.bbox()
                        bbox = BoundingBox(
                            x_min=float(ab[0]),
                            y_min=float(ab[1]),
                            x_max=float(ab[0] + ab[2]),
                            y_max=float(ab[1] + ab[3]),
                            confidence=pose_conf
                        )

                    fall_state = FallState.FALL_DETECTED if is_falling else FallState.NO_FALL
                    fall_confidence = 1.0 if is_falling else 0.0

                    person_detections.append(PersonDetection(
                        person_id=str(pid),
                        bbox=bbox,
                        keypoints=keypoints_list,
                        fall_state=fall_state,
                        fall_confidence=fall_confidence,
                        pose_confidence=pose_conf,
                        activity_label='falling' if is_falling else 'normal',
                        features={
                            'bbox_width': pw_,
                            'bbox_height': ph_,
                            'bbox_aspect_ratio': pw_ / ph_ if ph_ > 0 else 0.0,
                            'centroid_x': px,
                            'centroid_y': py,
                        }
                    ))

                frame_results.append(FrameResult(
                    frame_index=frame_idx,
                    timestamp_ms=timestamp_ms,
                    persons=person_detections,
                    fall_detected=fall_in_frame,
                ))

                framecount += 1
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
                'scale': scale,
                'frame_skip': frame_skip,
                'checkpoint': 'shufflenetv2k16w',
            },
            meta={
                'detector': self.name,
                'model': 'openpifpaf_0.11.8_shufflenetv2k16w',
                'device': str(self._device),
                'keypoint_format': 'coco_17',
                'coordinate_space': 'pixel_absolute',
                'fall_detection_method': 'rule_based_bbox_aspect_ratio_and_centroid_displacement',
                'fall_criteria': 'w >= 1.2*h AND centroid_displacement >= 0.5*bbox_diagonal',
            }
        )

    def cleanup(self) -> None:
        '''Release model resources.'''
        if hasattr(self, '_model'):
            del self._model
        if hasattr(self, '_processor'):
            del self._processor
        self._initialized = False
