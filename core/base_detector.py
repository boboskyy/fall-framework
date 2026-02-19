from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Generator
from datetime import datetime

from .models import (
    DetectionRequest,
    DetectionResponse,
    DetectionStatus,
    FrameResult,
    SensorWindow,
    InputType,
    FallState
)


class BaseDetector(ABC):

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._initialized = False


    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        pass

    @property
    @abstractmethod
    def supported_input_types(self) -> List[InputType]:
        pass


    @property
    def multi_person(self) -> bool:
        return False

    @property
    def requires_gpu(self) -> bool:
        return False


    @abstractmethod
    def initialize(self) -> None:
        pass

    def cleanup(self) -> None:
        pass


    @abstractmethod
    def detect(self, request: DetectionRequest) -> DetectionResponse:
        pass


    def detect_frame(self, frame, frame_index: int, timestamp_ms: float) -> FrameResult:
        raise NotImplementedError(f'{self.name} does not support frame-by-frame detection')

    def detect_sensor_window(self, readings, window_index: int) -> SensorWindow:
        raise NotImplementedError(f'{self.name} does not support sensor window detection')

    def stream_detect(self, request: DetectionRequest) -> Generator[FrameResult, None, None]:
        raise NotImplementedError(f'{self.name} does not support streaming detection')


    def validate_request(self, request: DetectionRequest) -> Optional[str]:
        if request.input_type not in self.supported_input_types:
            supported = [t.value for t in self.supported_input_types]
            return f'Detector {self.name} does not support input type {request.input_type.value}. Supported: {supported}'

        if not request.input_path and not request.input_url and not request.input_data:
            return 'No input source provided (input_path, input_url, or input_data required)'

        return None

    def get_info(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'version': self.version,
            'supported_input_types': [t.value for t in self.supported_input_types],
            'multi_person': self.multi_person,
            'requires_gpu': self.requires_gpu,
            'config': self.config,
            'initialized': self._initialized
        }


    def _build_response(
        self,
        frame_results: Optional[List[FrameResult]] = None,
        total_frames: int = 0,
        processed_frames: int = 0,
        sensor_results: Optional[List[SensorWindow]] = None,
        total_windows: int = 0,
        processed_windows: int = 0,
        processing_time_ms: Optional[float] = None,
        fall_events: Optional[List[Dict]] = None,
        summary: Optional[Dict] = None,
        meta: Optional[Dict] = None,
        config_used: Optional[Dict] = None,
        **kwargs
    ) -> DetectionResponse:
        if fall_events is None:
            fall_events = []
            if frame_results:
                for fr in frame_results:
                    if fr.fall_detected:
                        fall_events.append({
                            'frame_index': fr.frame_index,
                            'timestamp_ms': fr.timestamp_ms,
                            'persons': [p.person_id for p in fr.persons
                                       if p.fall_state in [FallState.FALL_DETECTED, FallState.FALLING]]
                        })
            elif sensor_results:
                for sw in sensor_results:
                    if sw.fall_detected:
                        fall_events.append({
                            'window_index': sw.window_index,
                            'start_timestamp_ms': sw.start_timestamp_ms,
                            'end_timestamp_ms': sw.end_timestamp_ms
                        })

        if summary is None:
            summary = {}
            if frame_results:
                fall_frame_count = sum(1 for fr in frame_results if fr.fall_detected)
                summary = {
                    'total_frames_analyzed': processed_frames,
                    'fall_frames_count': fall_frame_count,
                    'fall_percentage': (fall_frame_count / processed_frames * 100) if processed_frames > 0 else 0
                }
            elif sensor_results:
                fall_window_count = sum(1 for sw in sensor_results if sw.fall_detected)
                summary = {
                    'total_windows_analyzed': processed_windows,
                    'fall_windows_count': fall_window_count,
                    'fall_percentage': (fall_window_count / processed_windows * 100) if processed_windows > 0 else 0
                }

        response = DetectionResponse(
            task_id=kwargs.get('task_id', ''),
            status=DetectionStatus.COMPLETED,
            detector_name=self.name,
            detector_version=self.version,
            input_type=kwargs.get('input_type', InputType.VIDEO),
            total_frames=total_frames,
            processed_frames=processed_frames,
            frame_results=frame_results or [],
            total_windows=total_windows,
            processed_windows=processed_windows,
            sensor_results=sensor_results or [],
            fall_events=fall_events,
            summary=summary,
            processing_time_ms=processing_time_ms or 0.0,
            completed_at=datetime.utcnow().isoformat(),
            meta=meta or {},
            config_used=config_used
        )

        for key, value in kwargs.items():
            if hasattr(response, key):
                setattr(response, key, value)

        return response
