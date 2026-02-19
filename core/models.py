from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
import json
import uuid
from datetime import datetime


class InputType(Enum):
    VIDEO = 'video'
    IMAGE_SEQUENCE = 'image_sequence'
    RTSP_STREAM = 'rtsp_stream'
    DEPTH_VIDEO = 'depth_video'
    SENSOR_CSV = 'sensor_csv'
    SENSOR_STREAM = 'sensor_stream'


class DetectionStatus(Enum):
    PENDING = 'pending'
    QUEUED = 'queued'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class FallState(Enum):
    NO_FALL = 'no_fall'
    FALL_DETECTED = 'fall_detected'
    FALLING = 'falling'
    FALL_WARNING = 'fall_warning'
    LYING_DOWN = 'lying_down'
    RECOVERED = 'recovered'
    UNKNOWN = 'unknown'


class DetectorCategory(Enum):
    POSE_ESTIMATION = 'pose_estimation'
    OBJECT_DETECTION = 'object_detection'
    SENSOR_BASED = 'sensor_based'
    HYBRID = 'hybrid'


class ContainerStatus(Enum):
    NOT_DOWNLOADED = 'not_downloaded'
    NOT_BUILT = 'not_built'
    STOPPED = 'stopped'
    STARTING = 'starting'
    HEALTHY = 'healthy'
    UNHEALTHY = 'unhealthy'
    ERROR = 'error'


@dataclass
class Keypoint:
    name: str
    x: float
    y: float
    z: Optional[float] = None
    confidence: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BoundingBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    confidence: float = 0.0

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PersonDetection:
    person_id: str
    bbox: Optional[BoundingBox] = None
    keypoints: List[Keypoint] = field(default_factory=list)
    fall_state: FallState = FallState.UNKNOWN
    fall_confidence: Optional[float] = None
    pose_confidence: Optional[float] = None
    activity_label: Optional[str] = None
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'person_id': self.person_id,
            'bbox': self.bbox.to_dict() if self.bbox else None,
            'keypoints': [kp.to_dict() for kp in self.keypoints],
            'fall_state': self.fall_state.value,
            'fall_confidence': self.fall_confidence,
            'pose_confidence': self.pose_confidence,
            'activity_label': self.activity_label,
            'features': self.features
        }


@dataclass
class SensorReading:
    timestamp_ms: float
    accel_x: Optional[float] = None
    accel_y: Optional[float] = None
    accel_z: Optional[float] = None
    gyro_x: Optional[float] = None
    gyro_y: Optional[float] = None
    gyro_z: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SensorWindow:
    window_index: int
    start_timestamp_ms: float
    end_timestamp_ms: float
    readings: List[SensorReading] = field(default_factory=list)
    fall_detected: bool = False
    fall_confidence: Optional[float] = None
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'window_index': self.window_index,
            'start_timestamp_ms': self.start_timestamp_ms,
            'end_timestamp_ms': self.end_timestamp_ms,
            'readings': [r.to_dict() for r in self.readings],
            'fall_detected': self.fall_detected,
            'fall_confidence': self.fall_confidence,
            'features': self.features
        }


@dataclass
class FrameResult:
    frame_index: int
    timestamp_ms: float
    persons: List[PersonDetection] = field(default_factory=list)
    fall_detected: bool = False
    raw_output: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            'frame_index': self.frame_index,
            'timestamp_ms': self.timestamp_ms,
            'persons': [p.to_dict() for p in self.persons],
            'fall_detected': self.fall_detected,
            'raw_output': self.raw_output
        }


@dataclass
class DetectionRequest:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    input_type: InputType = InputType.VIDEO
    input_path: Optional[str] = None
    input_url: Optional[str] = None
    input_data: Optional[bytes] = None
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            'task_id': self.task_id,
            'input_type': self.input_type.value,
            'input_path': self.input_path,
            'input_url': self.input_url,
            'config': self.config,
            'created_at': self.created_at
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict) -> 'DetectionRequest':
        return cls(
            task_id=data.get('task_id', str(uuid.uuid4())),
            input_type=InputType(data.get('input_type', 'video')),
            input_path=data.get('input_path'),
            input_url=data.get('input_url'),
            config=data.get('config', {})
        )


@dataclass
class DetectionResponse:
    task_id: str
    status: DetectionStatus = DetectionStatus.PENDING
    detector_name: str = ''
    detector_version: str = ''
    input_type: InputType = InputType.VIDEO

    total_frames: int = 0
    processed_frames: int = 0
    frame_results: List[FrameResult] = field(default_factory=list)

    total_windows: int = 0
    processed_windows: int = 0
    sensor_results: List[SensorWindow] = field(default_factory=list)

    fall_events: List[Dict] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    processing_time_ms: float = 0.0
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    config_used: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        return {
            'task_id': self.task_id,
            'status': self.status.value,
            'detector_name': self.detector_name,
            'detector_version': self.detector_version,
            'input_type': self.input_type.value,
            'total_frames': self.total_frames,
            'processed_frames': self.processed_frames,
            'frame_results': [fr.to_dict() for fr in self.frame_results],
            'total_windows': self.total_windows,
            'processed_windows': self.processed_windows,
            'sensor_results': [sw.to_dict() for sw in self.sensor_results],
            'fall_events': self.fall_events,
            'summary': self.summary,
            'processing_time_ms': self.processing_time_ms,
            'error_message': self.error_message,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'meta': self.meta,
            'config_used': self.config_used
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict) -> 'DetectionResponse':
        frame_results = []
        for fr in data.get('frame_results', []):
            persons = []
            for p in fr.get('persons', []):
                keypoints = [Keypoint(**kp) for kp in p.get('keypoints', [])]
                bbox = BoundingBox(**p['bbox']) if p.get('bbox') else None
                persons.append(PersonDetection(
                    person_id=p['person_id'],
                    bbox=bbox,
                    keypoints=keypoints,
                    fall_state=FallState(p.get('fall_state', 'unknown')),
                    fall_confidence=p.get('fall_confidence'),
                    pose_confidence=p.get('pose_confidence'),
                    activity_label=p.get('activity_label'),
                    features=p.get('features', {})
                ))
            frame_results.append(FrameResult(
                frame_index=fr['frame_index'],
                timestamp_ms=fr['timestamp_ms'],
                persons=persons,
                fall_detected=fr.get('fall_detected', False),
                raw_output=fr.get('raw_output')
            ))

        sensor_results = []
        for sw in data.get('sensor_results', []):
            readings = [SensorReading(**r) for r in sw.get('readings', [])]
            sensor_results.append(SensorWindow(
                window_index=sw['window_index'],
                start_timestamp_ms=sw['start_timestamp_ms'],
                end_timestamp_ms=sw['end_timestamp_ms'],
                readings=readings,
                fall_detected=sw.get('fall_detected', False),
                fall_confidence=sw.get('fall_confidence'),
                features=sw.get('features', {})
            ))

        return cls(
            task_id=data['task_id'],
            status=DetectionStatus(data.get('status', 'pending')),
            detector_name=data.get('detector_name', ''),
            detector_version=data.get('detector_version', ''),
            input_type=InputType(data.get('input_type', 'video')),
            total_frames=data.get('total_frames', 0),
            processed_frames=data.get('processed_frames', 0),
            frame_results=frame_results,
            total_windows=data.get('total_windows', 0),
            processed_windows=data.get('processed_windows', 0),
            sensor_results=sensor_results,
            fall_events=data.get('fall_events', []),
            summary=data.get('summary', {}),
            processing_time_ms=data.get('processing_time_ms', 0.0),
            error_message=data.get('error_message'),
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at'),
            meta=data.get('meta', {}),
            config_used=data.get('config_used')
        )
