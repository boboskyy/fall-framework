
import uuid
import threading
import requests
from datetime import datetime
from typing import Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from gateway.models import OrchestrationJob, SubTask, JobStatus


class Orchestrator:

    def __init__(self, registry, timeout=600):
        self.registry = registry
        self.timeout = timeout
        self._jobs: Dict[str, OrchestrationJob] = {}

    def submit_single(self, input_path: str, input_type: str, detector_name: str,
                      config: Dict = None, sync: bool = False, label: str = None) -> Dict:
        validation = self.registry.validate_detectors([detector_name], input_type)
        if not validation['valid']:
            return {
                'error': 'INVALID_DETECTOR',
                'message': '; '.join(validation['errors'])
            }

        job_id = str(uuid.uuid4())
        job = OrchestrationJob(
            job_id=job_id,
            input_path=input_path,
            input_type=input_type,
            detector_names=[detector_name],
            config=config or {},
            label=label,
            status=JobStatus.PENDING.value
        )

        job.sub_tasks[detector_name] = SubTask(detector_name=detector_name)

        self._jobs[job_id] = job

        if sync:
            self._execute_single_sync(job, detector_name)
            return {
                'job_id': job_id,
                'label': job.label,
                'status': job.status,
                'result': job.sub_tasks[detector_name].result,
                'error': job.sub_tasks[detector_name].error
            }
        else:
            job.status = JobStatus.PENDING.value
            thread = threading.Thread(
                target=self._execute_single_sync,
                args=(job, detector_name),
                daemon=True
            )
            thread.start()
            return {
                'job_id': job_id,
                'label': job.label,
                'status': job.status
            }

    def submit_multi(self, input_path: str, input_type: str, detector_names: List[str],
                     config: Dict = None, sync: bool = False, label: str = None) -> Dict:
        validation = self.registry.validate_detectors(detector_names, input_type)
        if not validation['valid']:
            return {
                'error': 'INVALID_DETECTORS',
                'message': '; '.join(validation['errors']),
                'warnings': validation['warnings']
            }

        job_id = str(uuid.uuid4())
        job = OrchestrationJob(
            job_id=job_id,
            input_path=input_path,
            input_type=input_type,
            detector_names=detector_names,
            config=config or {},
            label=label,
            status=JobStatus.PENDING.value
        )

        for name in detector_names:
            job.sub_tasks[name] = SubTask(detector_name=name)

        self._jobs[job_id] = job

        if sync:
            self._execute_multi_sync(job)
            return {
                'job_id': job_id,
                'label': job.label,
                'status': job.status,
                'results': {name: task.result for name, task in job.sub_tasks.items()},
                'errors': {name: task.error for name, task in job.sub_tasks.items() if task.error}
            }
        else:
            job.status = JobStatus.PENDING.value
            thread = threading.Thread(
                target=self._execute_multi_sync,
                args=(job,),
                daemon=True
            )
            thread.start()
            return {
                'job_id': job_id,
                'label': job.label,
                'status': job.status
            }

    def _execute_multi_sync(self, job: OrchestrationJob):
        job.status = JobStatus.RUNNING.value
        job.started_at = datetime.utcnow().isoformat()

        with ThreadPoolExecutor(max_workers=len(job.detector_names)) as executor:
            future_to_detector = {
                executor.submit(self._execute_detector, job, name): name
                for name in job.detector_names
            }

            for future in as_completed(future_to_detector):
                detector_name = future_to_detector[future]
                try:
                    future.result()
                except Exception as e:
                    job.sub_tasks[detector_name].status = 'failed'
                    job.sub_tasks[detector_name].error = f'Executor error: {str(e)}'

        completed_count = sum(1 for t in job.sub_tasks.values() if t.status == 'completed')
        failed_count = sum(1 for t in job.sub_tasks.values() if t.status == 'failed')
        total_count = len(job.sub_tasks)

        if completed_count == total_count:
            job.status = JobStatus.COMPLETED.value
        elif failed_count == total_count:
            job.status = JobStatus.FAILED.value
        else:
            job.status = JobStatus.PARTIAL.value

        job.completed_at = datetime.utcnow().isoformat()

    def _execute_detector(self, job: OrchestrationJob, detector_name: str):
        sub_task = job.sub_tasks[detector_name]
        sub_task.status = 'running'
        sub_task.started_at = datetime.utcnow().isoformat()

        detector = self.registry.get_detector(detector_name)
        if not detector:
            sub_task.status = 'failed'
            sub_task.error = f'Detector {detector_name} not found'
            sub_task.completed_at = datetime.utcnow().isoformat()
            return

        if detector_name in job.config:
            detector_config = job.config[detector_name]
        else:
            detector_config = job.config

        payload = {
            'input_path': job.input_path,
            'input_type': job.input_type,
            'config': detector_config
        }

        url = f'http://{detector.docker_service_name}:{detector.internal_port}/detect/sync'

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)

            if response.status_code == 200:
                sub_task.status = 'completed'
                sub_task.result = response.json()
                sub_task.error = None
            else:
                sub_task.status = 'failed'
                sub_task.error = f'HTTP {response.status_code}: {response.text[:200]}'

        except requests.exceptions.Timeout:
            sub_task.status = 'failed'
            sub_task.error = f'Timeout after {self.timeout}s'

        except requests.exceptions.ConnectionError:
            sub_task.status = 'failed'
            sub_task.error = 'Container unreachable - is it running?'

        except Exception as e:
            sub_task.status = 'failed'
            sub_task.error = str(e)

        sub_task.completed_at = datetime.utcnow().isoformat()

    def _execute_single_sync(self, job: OrchestrationJob, detector_name: str):
        job.status = JobStatus.RUNNING.value
        job.started_at = datetime.utcnow().isoformat()

        self._execute_detector(job, detector_name)

        if job.sub_tasks[detector_name].status == 'completed':
            job.status = JobStatus.COMPLETED.value
        else:
            job.status = JobStatus.FAILED.value

        job.completed_at = datetime.utcnow().isoformat()

    def get_job(self, job_id: str) -> Optional[OrchestrationJob]:
        return self._jobs.get(job_id)

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.get_summary()

    def get_job_results(self, job_id: str) -> Optional[Dict]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.to_dict()

    def list_jobs(self) -> List[Dict]:
        return [job.get_summary() for job in self._jobs.values()]
