
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime


class GroundTruthType(Enum):
    VIDEO_LEVEL = 'video_level'
    FRAME_LEVEL = 'frame_level'
    NONE = 'none'


class DatasetFileLabel(Enum):
    FALL = 'FALL'
    ADL = 'ADL'
    UNLABELED = 'UNLABELED'


class DatasetStatus(Enum):
    AVAILABLE = 'available'
    DOWNLOADING = 'downloading'
    DOWNLOADED = 'downloaded'
    USER_UPLOADED = 'user_uploaded'


@dataclass
class DatasetFile:
    filename: str
    relative_path: str
    label: str                                    # 'FALL' / 'ADL' / 'UNLABELED'
    fall_detected_ground_truth: Optional[bool]    # None if UNLABELED
    annotations_path: Optional[str] = None        # For frame_level only
    size_bytes: int = 0
    duration_seconds: Optional[float] = None
    resolution: Optional[str] = None
    fps: Optional[float] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DatasetManifest:
    name: str
    display_name: str
    version: str
    description: str
    input_type: str                               # 'video' or 'sensor_csv'
    ground_truth_type: str                        # 'video_level' / 'frame_level' / 'none'
    files: List[DatasetFile]
    statistics: Dict[str, Any]
    source_url: Optional[str] = None
    label_map: Dict[str, bool] = field(default_factory=lambda: {'FALL': True, 'ADL': False})
    total_size_mb: Optional[float] = None

    @classmethod
    def from_file(cls, path: str) -> 'DatasetManifest':
        import json
        with open(path, 'r') as f:
            data = json.load(f)

        files = []
        for fd in data.get('files', []):
            files.append(DatasetFile(
                filename=fd['filename'],
                relative_path=fd['relative_path'],
                label=fd.get('label', 'UNLABELED'),
                fall_detected_ground_truth=fd.get('fall_detected_ground_truth'),
                annotations_path=fd.get('annotations_path'),
                size_bytes=fd.get('size_bytes', 0),
                duration_seconds=fd.get('duration_seconds'),
                resolution=fd.get('resolution'),
                fps=fd.get('fps'),
            ))

        return cls(
            name=data['name'],
            display_name=data.get('display_name', data['name']),
            version=data.get('version', '1.0.0'),
            description=data.get('description', ''),
            input_type=data.get('input_type', 'video'),
            ground_truth_type=data.get('ground_truth_type', 'none'),
            files=files,
            statistics=data.get('statistics', {}),
            source_url=data.get('source_url'),
            label_map=data.get('label_map', {'FALL': True, 'ADL': False}),
            total_size_mb=data.get('total_size_mb'),
        )

    def to_dict(self) -> Dict:
        data = asdict(self)
        return data

    def to_file(self, path: str) -> None:
        import json
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    def get_labeled_files(self) -> List[DatasetFile]:
        return [f for f in self.files if f.label != 'UNLABELED']

    def get_files_by_label(self, label: str) -> List[DatasetFile]:
        return [f for f in self.files if f.label == label]

    def recalculate_statistics(self) -> None:
        total = len(self.files)
        fall = sum(1 for f in self.files if f.label == 'FALL')
        adl = sum(1 for f in self.files if f.label == 'ADL')
        unlabeled = sum(1 for f in self.files if f.label == 'UNLABELED')
        durations = [f.duration_seconds for f in self.files if f.duration_seconds is not None]
        total_duration = sum(durations) if durations else 0
        avg_duration = total_duration / len(durations) if durations else 0

        self.statistics = {
            'total_files': total,
            'total_fall': fall,
            'total_adl': adl,
            'total_unlabeled': unlabeled,
            'avg_duration_seconds': round(avg_duration, 1),
            'total_duration_seconds': round(total_duration, 1),
        }


# --- Evaluation models ---

@dataclass
class EvaluationFileResult:
    """Result of running one detector on one dataset file."""
    filename: str
    ground_truth_label: str                       # 'FALL' / 'ADL' / 'UNLABELED'
    ground_truth_fall: Optional[bool]             # True/False/None
    detector_verdict: bool                        # Did detector say fall?
    detector_confidence: Optional[float]          # Aggregate confidence if available
    detector_fall_frame_count: int
    detector_total_frames: int
    detector_fall_percentage: float               # fall_frame_count / total_frames
    match: Optional[bool]                         # ground_truth_fall == detector_verdict (None if unlabeled)
    classification: Optional[str]                 # 'TP' / 'TN' / 'FP' / 'FN' / None
    processing_time_ms: int = 0
    frame_level_metrics: Optional[Dict] = None    # precision, recall, f1, temporal_iou

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['detector_verdict'] = 'FALL' if self.detector_verdict else 'ADL'
        return data


@dataclass
class EvaluationDetectorSummary:
    """Aggregate metrics for one detector across all evaluated files."""
    detector_name: str
    total_files: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    avg_processing_time_ms: float
    total_processing_time_ms: int
    avg_frame_precision: Optional[float] = None
    avg_frame_recall: Optional[float] = None
    avg_frame_f1: Optional[float] = None
    avg_temporal_iou: Optional[float] = None
    per_file_results: List[EvaluationFileResult] = field(default_factory=list)

    def to_dict(self) -> Dict:
        data = asdict(self)
        return data


@dataclass
class EvaluationJob:
    """Tracks an in-progress or completed evaluation.
    Follows the same pattern as OrchestrationJob, BatchJob, ComparisonJob."""
    eval_id: str
    dataset_name: str
    detector_names: List[str]
    selected_files: Optional[List[str]]           # None = all labeled files
    config: Optional[Dict]                        # Per-detector config
    verdict_config: Dict = field(default_factory=lambda: {
        'min_fall_frames': 1,
        'min_fall_percentage': 0.0,
    })
    status: str = 'pending'
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled: bool = False
    sub_tasks: Dict[str, Dict] = field(default_factory=dict)  # 'filename::detector' → {status, result, error}
    result: Optional['EvaluationResult'] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        data = {
            'eval_id': self.eval_id,
            'dataset_name': self.dataset_name,
            'detector_names': self.detector_names,
            'selected_files': self.selected_files,
            'verdict_config': self.verdict_config,
            'status': self.status,
            'total_tasks': self.total_tasks,
            'completed_tasks': self.completed_tasks,
            'failed_tasks': self.failed_tasks,
            'cancelled': self.cancelled,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'error': self.error,
        }
        if self.result:
            data['result'] = self.result.to_dict()
        return data

    def get_summary(self) -> Dict:
        progress_pct = round((self.completed_tasks / self.total_tasks) * 100, 1) if self.total_tasks > 0 else 0
        return {
            'eval_id': self.eval_id,
            'dataset_name': self.dataset_name,
            'detector_names': self.detector_names,
            'status': self.status,
            'total_tasks': self.total_tasks,
            'completed_tasks': self.completed_tasks,
            'failed_tasks': self.failed_tasks,
            'cancelled': self.cancelled,
            'progress_pct': progress_pct,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
        }


@dataclass
class EvaluationResult:
    """Complete evaluation result: dataset x N detectors."""
    eval_id: str
    dataset_name: str
    ground_truth_type: str
    total_files_evaluated: int
    total_files_in_dataset: int
    selected_files: Optional[List[str]]
    verdict_config: Dict
    detector_summaries: List[EvaluationDetectorSummary]
    cross_detector_agreement: Optional[Dict] = None
    overall_statistics: Optional[Dict] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    total_wall_time_seconds: Optional[float] = None
    status: str = 'completed'

    def to_dict(self) -> Dict:
        data = {
            'eval_id': self.eval_id,
            'dataset_name': self.dataset_name,
            'ground_truth_type': self.ground_truth_type,
            'total_files_evaluated': self.total_files_evaluated,
            'total_files_in_dataset': self.total_files_in_dataset,
            'selected_files': self.selected_files,
            'verdict_config': self.verdict_config,
            'detector_summaries': [s.to_dict() for s in self.detector_summaries],
            'cross_detector_agreement': self.cross_detector_agreement,
            'overall_statistics': self.overall_statistics,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'total_wall_time_seconds': self.total_wall_time_seconds,
            'status': self.status,
        }
        return data


@dataclass
class DatasetDownloadJob:
    """Tracks dataset download progress. Follows DownloadJob pattern."""
    download_id: str
    dataset_name: str
    status: str = 'downloading'                   # 'downloading' / 'completed' / 'failed'
    progress_bytes: int = 0
    total_bytes: int = 0
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    def get_summary(self) -> Dict:
        pct = round((self.progress_bytes / self.total_bytes) * 100, 1) if self.total_bytes > 0 else 0
        return {
            'download_id': self.download_id,
            'dataset': self.dataset_name,
            'status': self.status,
            'progress_pct': pct,
            'progress_mb': round(self.progress_bytes / (1024 * 1024), 1),
            'total_mb': round(self.total_bytes / (1024 * 1024), 1),
            'error': self.error,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
        }
