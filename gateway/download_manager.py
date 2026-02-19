
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import threading
import uuid
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from gateway.config import DETECTOR_REPO_BASE_URL
from gateway.models import DownloadJob, DownloadStatus, ContainerStatus


class DownloadManager:

    def __init__(self, registry, detectors_dir='/detectors'):
        self.registry = registry
        self.detectors_dir = detectors_dir
        self.base_url = DETECTOR_REPO_BASE_URL
        self._downloads: Dict[str, DownloadJob] = {}
        self._lock = threading.Lock()

    def submit_download(self, detector_name: str, force: bool = False) -> Dict:
        detector = self.registry.get_detector(detector_name)
        if not detector:
            return {
                'error': 'NOT_FOUND',
                'message': f'Detector "{detector_name}" not found'
            }

        manifest = self.registry.get_manifest(detector_name)
        if not manifest:
            return {
                'error': 'NOT_FOUND',
                'message': f'No manifest found for "{detector_name}"'
            }

        download_config = manifest.get('download')
        if not download_config:
            return {
                'error': 'NO_DOWNLOAD_CONFIG',
                'message': f'Detector "{detector_name}" has no download configuration '
                           f'(custom detector — repo is provided locally)'
            }

        if not force and self.registry._is_downloaded(detector_name, download_config):
            return {
                'error': 'ALREADY_DOWNLOADED',
                'message': f'Detector "{detector_name}" repo already downloaded. '
                           f'Use force=true to re-download.'
            }

        with self._lock:
            for dl in self._downloads.values():
                if (dl.detector_name == detector_name
                        and dl.status == DownloadStatus.DOWNLOADING.value):
                    return {
                        'error': 'ALREADY_DOWNLOADING',
                        'message': f'Detector "{detector_name}" is already being downloaded',
                        'download_id': dl.download_id
                    }

            download_id = f'dl-{uuid.uuid4()}'
            total_bytes = download_config.get('size_mb', 0) * 1024 * 1024
            download_job = DownloadJob(
                download_id=download_id,
                detector_name=detector_name,
                total_bytes=int(total_bytes)
            )
            self._downloads[download_id] = download_job

        detector.container_status = ContainerStatus.DOWNLOADING.value

        thread = threading.Thread(
            target=self._execute_download,
            args=(download_id, download_config, force),
            daemon=True
        )
        thread.start()

        return {
            'download_id': download_id,
            'detector': detector_name,
            'status': download_job.status
        }

    def _execute_download(self, download_id: str, download_config: dict,
                          force: bool = False):
        download_job = self._downloads[download_id]
        detector_name = download_job.detector_name
        detector_dir = Path(self.detectors_dir) / detector_name
        marker_path = detector_dir / '.download_complete'
        archive_name = download_config['archive_name']
        extract_to = download_config.get('extract_to', 'repo')
        expected_sha256 = download_config.get('sha256')
        url = self.base_url.rstrip('/') + '/' + archive_name

        tmp_file = None
        try:
            if force:
                target_dir = detector_dir / extract_to if extract_to != '.' else detector_dir
                if extract_to != '.':
                    if target_dir.exists():
                        shutil.rmtree(target_dir)
                if marker_path.exists():
                    marker_path.unlink()

            tmp_fd, tmp_path = tempfile.mkstemp(suffix='.tar.gz', dir=str(detector_dir))
            os.close(tmp_fd)
            tmp_file = tmp_path

            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=300) as response:
                content_length = response.headers.get('Content-Length')
                if content_length:
                    download_job.total_bytes = int(content_length)

                hasher = hashlib.sha256()
                bytes_read = 0
                chunk_size = 64 * 1024

                with open(tmp_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        hasher.update(chunk)
                        bytes_read += len(chunk)
                        download_job.progress_bytes = bytes_read

            actual_sha256 = hasher.hexdigest()
            if expected_sha256 and actual_sha256 != expected_sha256:
                raise ValueError(
                    f'SHA256 mismatch: expected {expected_sha256}, '
                    f'got {actual_sha256}'
                )

            if extract_to != '.':
                target_dir = detector_dir / extract_to
                if target_dir.exists():
                    shutil.rmtree(target_dir)
            else:
                models_dir = detector_dir / 'models'
                if models_dir.exists():
                    shutil.rmtree(models_dir)
            if marker_path.exists():
                marker_path.unlink()

            with tarfile.open(tmp_path, 'r:gz') as tar:
                try:
                    tar.extractall(path=str(detector_dir), filter='data')
                except TypeError:
                    tar.extractall(path=str(detector_dir))

            marker_data = {
                'sha256': actual_sha256,
                'downloaded_at': datetime.utcnow().isoformat(),
                'version': 'v1.0',
                'archive_name': archive_name
            }
            with open(marker_path, 'w') as f:
                json.dump(marker_data, f, indent=2)

            download_job.status = DownloadStatus.COMPLETED.value
            download_job.completed_at = datetime.utcnow().isoformat()

            detector = self.registry.get_detector(detector_name)
            if detector:
                detector.container_status = ContainerStatus.NOT_BUILT.value

        except Exception as e:
            download_job.status = DownloadStatus.FAILED.value
            download_job.error = str(e)
            download_job.completed_at = datetime.utcnow().isoformat()

            detector = self.registry.get_detector(detector_name)
            if detector and detector.container_status == ContainerStatus.DOWNLOADING.value:
                detector.container_status = ContainerStatus.NOT_DOWNLOADED.value

        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.unlink(tmp_file)
                except OSError:
                    pass

    def delete_download(self, detector_name: str) -> Dict:
        detector = self.registry.get_detector(detector_name)
        if not detector:
            return {
                'error': 'NOT_FOUND',
                'message': f'Detector "{detector_name}" not found'
            }

        manifest = self.registry.get_manifest(detector_name)
        if not manifest:
            return {
                'error': 'NOT_FOUND',
                'message': f'No manifest found for "{detector_name}"'
            }

        download_config = manifest.get('download')
        if not download_config:
            return {
                'error': 'NO_DOWNLOAD_CONFIG',
                'message': f'Detector "{detector_name}" has no download configuration'
            }

        detector_dir = Path(self.detectors_dir) / detector_name
        extract_to = download_config.get('extract_to', 'repo')
        marker_path = detector_dir / '.download_complete'

        removed_files = False

        if extract_to == '.':
            models_dir = detector_dir / 'models'
            if models_dir.exists():
                shutil.rmtree(models_dir)
                removed_files = True
        else:
            target_dir = detector_dir / extract_to
            if target_dir.exists():
                shutil.rmtree(target_dir)
                removed_files = True

        if marker_path.exists():
            marker_path.unlink()
            removed_files = True

        if not removed_files:
            return {
                'status': 'nothing_to_remove',
                'detector': detector_name,
                'message': f'No downloaded files found for "{detector_name}"'
            }

        detector.container_status = ContainerStatus.NOT_DOWNLOADED.value
        return {
            'status': 'deleted',
            'detector': detector_name,
            'message': f'Downloaded repo for "{detector_name}" removed'
        }

    def get_download(self, download_id: str) -> Optional[DownloadJob]:
        return self._downloads.get(download_id)

    def list_downloads(self) -> List[Dict]:
        return [d.get_summary() for d in self._downloads.values()]
