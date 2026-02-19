
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from gateway.models import BatchJob
from gateway.file_manager import FileManager


class BatchManager:

    def __init__(self, orchestrator, file_manager: Optional[FileManager] = None):
        self.orchestrator = orchestrator
        self.file_manager = file_manager or FileManager()
        self._batches: Dict[str, BatchJob] = {}

    def create_batch(self, zip_path: str, detector_names: List[str],
                     input_type: str = 'video', config: Dict = None,
                     label: str = None) -> BatchJob:
        batch_id = f'b-{uuid.uuid4()}'

        try:
            input_files = self.file_manager.extract_zip(zip_path, batch_id, input_type)
        except ValueError as e:
            raise ValueError(f'Batch creation failed: {str(e)}')

        batch = BatchJob(
            batch_id=batch_id,
            input_files=input_files,
            detector_names=detector_names,
            input_type=input_type,
            config=config or {},
            label=label,
            status='pending'
        )

        self._batches[batch_id] = batch
        return batch

    def start_batch(self, batch_id: str) -> BatchJob:
        batch = self._batches.get(batch_id)
        if not batch:
            raise ValueError(f'Batch {batch_id} not found')

        batch.status = 'running'
        batch.started_at = datetime.utcnow().isoformat()

        for input_file in batch.input_files:
            try:
                job_result = self.orchestrator.submit_multi(
                    input_path=input_file,
                    input_type=batch.input_type,
                    detector_names=batch.detector_names,
                    config=batch.config,
                    sync=True
                )

                batch.orchestration_jobs.append(job_result['job_id'])

            except Exception as e:
                batch.orchestration_jobs.append(None)

                if 'errors' not in batch.meta:
                    batch.meta['errors'] = []
                batch.meta['errors'].append({
                    'file': input_file,
                    'error': str(e)
                })

        self._update_batch_status(batch)

        return batch

    def _update_batch_status(self, batch: BatchJob):
        total_count = len(batch.input_files)

        if total_count == 0:
            batch.status = 'failed'
            if not batch.completed_at:
                batch.completed_at = datetime.utcnow().isoformat()
            return

        completed_count = 0
        failed_count = 0

        for job_id in batch.orchestration_jobs:
            if job_id is None:
                failed_count += 1
                continue

            job = self.orchestrator.get_job(job_id)
            if job:
                if job.status == 'completed':
                    completed_count += 1
                elif job.status == 'failed':
                    failed_count += 1

        if completed_count == total_count:
            batch.status = 'completed'
        elif failed_count == total_count:
            batch.status = 'failed'
        elif completed_count + failed_count == total_count:
            batch.status = 'partial'
        else:
            batch.status = 'running'

        if batch.status in ['completed', 'failed', 'partial'] and not batch.completed_at:
            batch.completed_at = datetime.utcnow().isoformat()

    def get_batch_status(self, batch_id: str) -> Optional[Dict]:
        batch = self._batches.get(batch_id)
        if not batch:
            return None

        self._update_batch_status(batch)

        total_tasks = len(batch.input_files) * len(batch.detector_names)
        completed_tasks = 0
        failed_tasks = 0
        running_tasks = 0

        for job_id in batch.orchestration_jobs:
            if job_id is None:
                failed_tasks += len(batch.detector_names)
                continue

            job = self.orchestrator.get_job(job_id)
            if job:
                for sub_task in job.sub_tasks.values():
                    if sub_task.status == 'completed':
                        completed_tasks += 1
                    elif sub_task.status == 'failed':
                        failed_tasks += 1
                    elif sub_task.status == 'running':
                        running_tasks += 1

        progress_pct = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

        return {
            'batch_id': batch.batch_id,
            'label': batch.label,
            'status': batch.status,
            'created_at': batch.created_at,
            'started_at': batch.started_at,
            'completed_at': batch.completed_at,
            'progress': {
                'total_files': len(batch.input_files),
                'total_tasks': total_tasks,
                'completed_tasks': completed_tasks,
                'failed_tasks': failed_tasks,
                'running_tasks': running_tasks,
                'progress_pct': round(progress_pct, 1)
            },
            'files': [Path(f).name for f in batch.input_files],
            'detectors': batch.detector_names
        }

    def get_batch_results(self, batch_id: str) -> Optional[Dict]:
        batch = self._batches.get(batch_id)
        if not batch:
            return None

        self._update_batch_status(batch)

        results_by_file = {}

        for i, input_file in enumerate(batch.input_files):
            filename = Path(input_file).name

            if i < len(batch.orchestration_jobs):
                job_id = batch.orchestration_jobs[i]

                if job_id is None:
                    results_by_file[filename] = {
                        'error': 'File failed to process - see batch errors'
                    }
                    continue

                job = self.orchestrator.get_job(job_id)

                if job:
                    detector_results = {}
                    for detector_name, sub_task in job.sub_tasks.items():
                        detector_results[detector_name] = sub_task.result

                    results_by_file[filename] = detector_results

        return {
            'batch_id': batch.batch_id,
            'label': batch.label,
            'status': batch.status,
            'created_at': batch.created_at,
            'started_at': batch.started_at,
            'completed_at': batch.completed_at,
            'input_type': batch.input_type,
            'total_files': len(batch.input_files),
            'total_detectors': len(batch.detector_names),
            'detectors': batch.detector_names,
            'results': results_by_file,
            'errors': batch.meta.get('errors', [])
        }

    def get_batch(self, batch_id: str) -> Optional[BatchJob]:
        return self._batches.get(batch_id)

    def list_batches(self) -> List[Dict]:
        batches = []
        for batch in self._batches.values():
            self._update_batch_status(batch)
            batches.append({
                'batch_id': batch.batch_id,
                'label': batch.label,
                'status': batch.status,
                'created_at': batch.created_at,
                'total_files': len(batch.input_files),
                'total_detectors': len(batch.detector_names),
                'total_tasks': len(batch.input_files) * len(batch.detector_names)
            })
        return batches

    def delete_batch(self, batch_id: str) -> bool:
        batch = self._batches.get(batch_id)
        if not batch:
            return False

        self.file_manager.delete_batch_files(batch_id)

        del self._batches[batch_id]

        return True
