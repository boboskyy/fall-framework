from typing import Dict, Optional
from datetime import datetime
import threading
import queue
from .models import DetectionRequest, DetectionResponse, DetectionStatus


class TaskManager:
    
    def __init__(self):
        self._tasks: Dict[str, DetectionResponse] = {}
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
    
    def create_task(self, request: DetectionRequest) -> str:
        response = DetectionResponse(
            task_id=request.task_id,
            status=DetectionStatus.PENDING,
            input_type=request.input_type,
            created_at=datetime.utcnow().isoformat()
        )
        with self._lock:
            self._tasks[request.task_id] = response
        return request.task_id
    
    def get_task(self, task_id: str) -> Optional[DetectionResponse]:
        with self._lock:
            return self._tasks.get(task_id)
    
    def update_task(self, task_id: str, **kwargs) -> None:
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                for key, value in kwargs.items():
                    if hasattr(task, key):
                        setattr(task, key, value)
    
    def set_processing(self, task_id: str) -> None:
        self.update_task(task_id, status=DetectionStatus.PROCESSING)
    
    def set_completed(self, task_id: str, response: DetectionResponse) -> None:
        with self._lock:
            response.status = DetectionStatus.COMPLETED
            response.completed_at = datetime.utcnow().isoformat()
            self._tasks[task_id] = response
    
    def set_failed(self, task_id: str, error: str) -> None:
        self.update_task(
            task_id,
            status=DetectionStatus.FAILED,
            error_message=error,
            completed_at=datetime.utcnow().isoformat()
        )
    
    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False
    
    def list_tasks(self) -> Dict[str, dict]:
        with self._lock:
            return {
                tid: {
                    "status": t.status.value,
                    "created_at": t.created_at,
                    "completed_at": t.completed_at
                }
                for tid, t in self._tasks.items()
            }
