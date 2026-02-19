
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime


class BuildStatus(Enum):
    QUEUED = 'queued'
    BUILDING = 'building'
    BUILT = 'built'
    FAILED = 'failed'


class JobStatus(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    PARTIAL = 'partial'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class ContainerStatus(Enum):
    NOT_DOWNLOADED = 'not_downloaded'
    DOWNLOADING = 'downloading'
    NOT_BUILT = 'not_built'
    BUILDING = 'building'
    STOPPED = 'stopped'
    STARTING = 'starting'
    HEALTHY = 'healthy'
    UNHEALTHY = 'unhealthy'
    ERROR = 'error'


@dataclass
class DetectorInfo:
    name: str
    display_name: str
    version: str
    description: str
    category: str
    port: int
    internal_port: int
    docker_service_name: str
    supported_input_types: List[str]
    multi_person: bool
    requires_gpu: bool
    github_url: str = ''
    tags: List[str] = field(default_factory=list)
    gpu_capable: bool = False
    device: str = 'cpu'
    container_status: str = 'unknown'
    last_health_check: Optional[str] = None
    health_check_error: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SubTask:
    detector_name: str
    status: str = 'pending'
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class OrchestrationJob:
    job_id: str
    input_path: str
    input_type: str
    detector_names: List[str]
    config: Dict = field(default_factory=dict)
    label: Optional[str] = None
    status: str = 'pending'
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    sub_tasks: Dict[str, SubTask] = field(default_factory=dict)
    meta: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['sub_tasks'] = {k: v.to_dict() if hasattr(v, 'to_dict') else v
                             for k, v in self.sub_tasks.items()}
        return data

    def get_summary(self) -> Dict:
        return {
            'job_id': self.job_id,
            'label': self.label,
            'input_path': self.input_path,
            'input_type': self.input_type,
            'detector_names': self.detector_names,
            'status': self.status,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'sub_task_statuses': {
                name: task.status for name, task in self.sub_tasks.items()
            },
            'progress': self._calculate_progress()
        }

    def _calculate_progress(self) -> Dict:
        total = len(self.sub_tasks)
        if total == 0:
            return {'total': 0, 'completed': 0, 'running': 0, 'failed': 0, 'progress_pct': 0}

        completed = sum(1 for t in self.sub_tasks.values() if t.status == 'completed')
        running = sum(1 for t in self.sub_tasks.values() if t.status == 'running')
        failed = sum(1 for t in self.sub_tasks.values() if t.status == 'failed')

        return {
            'total': total,
            'completed': completed,
            'running': running,
            'failed': failed,
            'progress_pct': round((completed / total) * 100, 1)
        }


@dataclass
class BatchJob:
    batch_id: str
    input_files: List[str]
    detector_names: List[str]
    input_type: str
    config: Dict = field(default_factory=dict)
    label: Optional[str] = None
    status: str = 'pending'
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    orchestration_jobs: List[str] = field(default_factory=list)
    meta: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ComparisonJob:
    comparison_id: str
    job_id: str
    detectors: List[str]
    input_file: str
    input_type: str
    label: Optional[str] = None
    status: str = 'pending'
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    comparison_result: Optional[Dict] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    def get_summary(self) -> Dict:
        if self.status in ['pending', 'running']:
            return {
                'comparison_id': self.comparison_id,
                'label': self.label,
                'job_id': self.job_id,
                'status': self.status,
                'detectors': self.detectors,
                'created_at': self.created_at
            }
        else:
            base = {
                'comparison_id': self.comparison_id,
                'label': self.label,
                'status': self.status,
                'created_at': self.created_at,
                'completed_at': self.completed_at
            }
            if self.error:
                base['error'] = self.error
            if self.comparison_result:
                base.update(self.comparison_result)
            return base


@dataclass
class ComparisonResult:
    comparison_id: str
    job_id: str
    detectors: List[str]
    input_file: str
    status: str
    created_at: str
    completed_at: str
    detector_summaries: List[Dict]
    agreement_matrix: Dict
    event_comparison: Dict
    unified_timeline: Dict
    comparison_notes: List[str] = field(default_factory=list)
    detector_capabilities: Dict = field(default_factory=dict)
    results: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BuildJob:
    build_id: str
    detector_name: str
    service_name: str
    status: str = BuildStatus.QUEUED.value
    log_output: str = ''
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    def get_summary(self) -> Dict:
        return {
            'build_id': self.build_id,
            'detector': self.detector_name,
            'service': self.service_name,
            'status': self.status,
            'log': self.log_output[-2000:] if self.log_output else '',
            'error': self.error,
            'created_at': self.created_at,
            'completed_at': self.completed_at
        }


class DownloadStatus(Enum):
    DOWNLOADING = 'downloading'
    COMPLETED = 'completed'
    FAILED = 'failed'


@dataclass
class DownloadJob:
    download_id: str
    detector_name: str
    status: str = DownloadStatus.DOWNLOADING.value
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
            'detector': self.detector_name,
            'status': self.status,
            'progress_pct': pct,
            'progress_mb': round(self.progress_bytes / (1024 * 1024), 1),
            'total_mb': round(self.total_bytes / (1024 * 1024), 1),
            'error': self.error,
            'created_at': self.created_at,
            'completed_at': self.completed_at
        }
