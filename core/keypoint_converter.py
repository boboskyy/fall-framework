from typing import List, Dict, Optional
from .models import Keypoint


OPENPIFPAF_KEYPOINTS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle"
]

MEDIAPIPE_KEYPOINTS = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index"
]

CANONICAL_KEYPOINTS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle"
]

MEDIAPIPE_TO_CANONICAL = {
    "nose": "nose",
    "left_eye": "left_eye",
    "right_eye": "right_eye",
    "left_ear": "left_ear",
    "right_ear": "right_ear",
    "left_shoulder": "left_shoulder",
    "right_shoulder": "right_shoulder",
    "left_elbow": "left_elbow",
    "right_elbow": "right_elbow",
    "left_wrist": "left_wrist",
    "right_wrist": "right_wrist",
    "left_hip": "left_hip",
    "right_hip": "right_hip",
    "left_knee": "left_knee",
    "right_knee": "right_knee",
    "left_ankle": "left_ankle",
    "right_ankle": "right_ankle"
}


class KeypointConverter:
    
    @staticmethod
    def from_openpifpaf(data: list, confidence_threshold: float = 0.0) -> List[Keypoint]:
        keypoints = []
        for i, name in enumerate(OPENPIFPAF_KEYPOINTS):
            if i * 3 + 2 < len(data):
                x = data[i * 3]
                y = data[i * 3 + 1]
                conf = data[i * 3 + 2]
                if conf >= confidence_threshold:
                    keypoints.append(Keypoint(name=name, x=x, y=y, confidence=conf))
        return keypoints
    
    @staticmethod
    def from_openpifpaf_prediction(prediction) -> List[Keypoint]:
        keypoints = []
        if hasattr(prediction, 'data'):
            data = prediction.data
            for i, name in enumerate(OPENPIFPAF_KEYPOINTS):
                if i < len(data):
                    x, y, conf = data[i]
                    keypoints.append(Keypoint(name=name, x=float(x), y=float(y), confidence=float(conf)))
        return keypoints
    
    @staticmethod
    def from_mediapipe(landmarks, width: int = 1, height: int = 1) -> List[Keypoint]:
        keypoints = []
        if landmarks:
            for i, name in enumerate(MEDIAPIPE_KEYPOINTS):
                if i < len(landmarks.landmark):
                    lm = landmarks.landmark[i]
                    canonical_name = MEDIAPIPE_TO_CANONICAL.get(name)
                    if canonical_name:
                        keypoints.append(Keypoint(
                            name=canonical_name,
                            x=lm.x * width,
                            y=lm.y * height,
                            z=lm.z if hasattr(lm, 'z') else None,
                            confidence=lm.visibility if hasattr(lm, 'visibility') else 1.0
                        ))
        return keypoints
    
    @staticmethod
    def from_yolo(keypoints_data, names: Optional[List[str]] = None) -> List[Keypoint]:
        keypoints = []
        kp_names = names or CANONICAL_KEYPOINTS
        if keypoints_data is not None:
            for i, kp in enumerate(keypoints_data):
                if i < len(kp_names):
                    if len(kp) >= 2:
                        keypoints.append(Keypoint(
                            name=kp_names[i],
                            x=float(kp[0]),
                            y=float(kp[1]),
                            confidence=float(kp[2]) if len(kp) > 2 else 1.0
                        ))
        return keypoints
    
    @staticmethod
    def from_posenet(keypoints_data: List[Dict]) -> List[Keypoint]:
        keypoints = []
        for kp in keypoints_data:
            keypoints.append(Keypoint(
                name=kp.get("part", "unknown"),
                x=kp.get("position", {}).get("x", 0),
                y=kp.get("position", {}).get("y", 0),
                confidence=kp.get("score", 0.0)
            ))
        return keypoints
    
    @staticmethod
    def to_canonical(keypoints: List[Keypoint]) -> Dict[str, Keypoint]:
        return {kp.name: kp for kp in keypoints if kp.name in CANONICAL_KEYPOINTS}
