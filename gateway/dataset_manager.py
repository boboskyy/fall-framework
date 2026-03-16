
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
import urllib.request
import urllib.error
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from gateway.dataset_models import (
    DatasetManifest, DatasetFile, DatasetDownloadJob,
)


VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'}
SENSOR_EXTENSIONS = {'.csv'}

FALL_FOLDER_NAMES = {'fall', 'falls', 'falling'}
ADL_FOLDER_NAMES = {'adl', 'normal', 'daily', 'notfall', 'not_fall', 'no_fall', 'standing', 'walking', 'sitting'}


class DatasetManager:

    def __init__(self, datasets_dir: str = '/datasets',
                 shared_dir: str = '/shared',
                 registry_url: str = ''):
        self.datasets_dir = Path(datasets_dir)
        self.shared_dir = Path(shared_dir)
        self.datasets_shared_dir = self.shared_dir / 'datasets'
        self.registry_url = registry_url
        self._registry_cache: Optional[Dict] = None
        self._datasets: Dict[str, DatasetManifest] = {}
        self._downloads: Dict[str, DatasetDownloadJob] = {}
        self._lock = threading.Lock()

        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self.datasets_shared_dir.mkdir(parents=True, exist_ok=True)

        self._scan_local_datasets()

    # === Startup scan ===

    def _scan_local_datasets(self):
        if not self.datasets_dir.exists():
            return
        for entry in self.datasets_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith('_'):
                continue
            manifest_path = entry / 'dataset_manifest.json'
            if manifest_path.exists():
                try:
                    manifest = DatasetManifest.from_file(str(manifest_path))
                    self._datasets[manifest.name] = manifest
                except Exception:
                    pass

    # === Registry ===

    def refresh_registry(self) -> Dict:
        if not self.registry_url:
            return {'available': [], 'downloaded': list(self._datasets.keys())}

        try:
            req = urllib.request.Request(self.registry_url)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))

            cache_path = self.datasets_dir / '_registry_cache.json'
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)

            self._registry_cache = data
        except Exception as e:
            cache_path = self.datasets_dir / '_registry_cache.json'
            if cache_path.exists():
                with open(cache_path, 'r') as f:
                    self._registry_cache = json.load(f)
            else:
                return {'error': str(e), 'downloaded': list(self._datasets.keys())}

        available = []
        for ds in self._registry_cache.get('datasets', []):
            if ds['name'] not in self._datasets:
                available.append(ds['name'])

        return {
            'available': available,
            'downloaded': list(self._datasets.keys()),
        }

    def _get_registry_entry(self, name: str) -> Optional[Dict]:
        if self._registry_cache is None:
            cache_path = self.datasets_dir / '_registry_cache.json'
            if cache_path.exists():
                with open(cache_path, 'r') as f:
                    self._registry_cache = json.load(f)

        if self._registry_cache:
            for ds in self._registry_cache.get('datasets', []):
                if ds['name'] == name:
                    return ds
        return None

    # === Listing ===

    def list_datasets(self) -> List[Dict]:
        result = []

        for name, manifest in self._datasets.items():
            dataset_dir = self.datasets_dir / name
            is_user_uploaded = (dataset_dir / '.user_uploaded').exists()
            status = 'user_uploaded' if is_user_uploaded else 'downloaded'
            stats = manifest.statistics
            result.append({
                'name': name,
                'display_name': manifest.display_name,
                'status': status,
                'ground_truth_type': manifest.ground_truth_type,
                'input_type': manifest.input_type,
                'total_files': stats.get('total_files', len(manifest.files)),
                'labeled_files': stats.get('total_files', 0) - stats.get('total_unlabeled', 0),
                'total_fall': stats.get('total_fall', 0),
                'total_adl': stats.get('total_adl', 0),
                'size_mb': manifest.total_size_mb,
            })

        if self._registry_cache:
            for ds in self._registry_cache.get('datasets', []):
                if ds['name'] not in self._datasets:
                    downloading = False
                    for dl in self._downloads.values():
                        if dl.dataset_name == ds['name'] and dl.status == 'downloading':
                            downloading = True
                            break
                    result.append({
                        'name': ds['name'],
                        'display_name': ds.get('display_name', ds['name']),
                        'status': 'downloading' if downloading else 'available',
                        'ground_truth_type': ds.get('ground_truth_type', 'none'),
                        'input_type': ds.get('input_type', 'video'),
                        'total_files': ds.get('total_files', 0),
                        'labeled_files': ds.get('total_fall', 0) + ds.get('total_adl', 0),
                        'total_fall': ds.get('total_fall', 0),
                        'total_adl': ds.get('total_adl', 0),
                        'size_mb': ds.get('size_mb'),
                        'download_url': ds.get('download_url'),
                    })

        return result

    def get_dataset_info(self, name: str) -> Optional[Dict]:
        manifest = self._datasets.get(name)
        if manifest:
            dataset_dir = self.datasets_dir / name
            is_user_uploaded = (dataset_dir / '.user_uploaded').exists()
            info = manifest.to_dict()
            info['status'] = 'user_uploaded' if is_user_uploaded else 'downloaded'
            # Flatten statistics + size to top level for frontend compatibility
            stats = manifest.statistics
            info['total_files'] = stats.get('total_files', len(manifest.files))
            info['total_fall'] = stats.get('total_fall', 0)
            info['total_adl'] = stats.get('total_adl', 0)
            info['total_unlabeled'] = stats.get('total_unlabeled', 0)
            info['size_mb'] = manifest.total_size_mb or 0
            return info

        entry = self._get_registry_entry(name)
        if entry:
            entry['status'] = 'available'
            return entry

        return None

    def get_dataset_files(self, name: str, label: str = None,
                          page: int = 1, per_page: int = 50) -> Optional[Dict]:
        manifest = self._datasets.get(name)
        if not manifest:
            return None

        files = manifest.files
        if label:
            files = [f for f in files if f.label == label.upper()]

        total = len(files)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        page_files = files[start:end]

        return {
            'dataset_name': name,
            'ground_truth_type': manifest.ground_truth_type,
            'total_files': total,
            'files': [
                {
                    'filename': f.filename,
                    'relative_path': f.relative_path,
                    'label': f.label,
                    'fall_detected_ground_truth': f.fall_detected_ground_truth,
                    'has_annotations': f.annotations_path is not None,
                    'size_bytes': f.size_bytes,
                    'duration_seconds': f.duration_seconds,
                    'resolution': f.resolution,
                    'fps': f.fps,
                }
                for f in page_files
            ],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_pages': total_pages,
            },
        }

    # === Download ===

    def download_dataset(self, name: str) -> Dict:
        if name in self._datasets:
            return {
                'error': 'ALREADY_DOWNLOADED',
                'message': f'Dataset "{name}" is already downloaded',
            }

        entry = self._get_registry_entry(name)
        if not entry:
            return {
                'error': 'NOT_FOUND',
                'message': f'Dataset "{name}" not found in registry',
            }

        download_url = entry.get('download_url')
        if not download_url:
            return {
                'error': 'NO_DOWNLOAD_URL',
                'message': f'No download URL for dataset "{name}"',
            }

        with self._lock:
            for dl in self._downloads.values():
                if dl.dataset_name == name and dl.status == 'downloading':
                    return {
                        'error': 'ALREADY_DOWNLOADING',
                        'message': f'Dataset "{name}" is already being downloaded',
                        'download_id': dl.download_id,
                    }

            download_id = f'dsdl-{uuid.uuid4().hex[:8]}'
            total_bytes = entry.get('size_mb', 0) * 1024 * 1024
            job = DatasetDownloadJob(
                download_id=download_id,
                dataset_name=name,
                total_bytes=int(total_bytes),
            )
            self._downloads[download_id] = job

        expected_sha256 = entry.get('checksum_sha256')

        thread = threading.Thread(
            target=self._execute_download,
            args=(download_id, download_url, expected_sha256),
            daemon=True,
        )
        thread.start()

        return {
            'download_id': download_id,
            'status': 'downloading',
            'name': name,
        }

    def _execute_download(self, download_id: str, download_url: str,
                          expected_sha256: str = None):
        job = self._downloads[download_id]
        name = job.dataset_name
        dataset_dir = self.datasets_dir / name
        marker_path = dataset_dir / '.download_complete'

        tmp_file = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix='.zip')
            os.close(tmp_fd)
            tmp_file = tmp_path

            req = urllib.request.Request(download_url)
            with urllib.request.urlopen(req, timeout=600) as response:
                content_length = response.headers.get('Content-Length')
                if content_length:
                    job.total_bytes = int(content_length)

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
                        job.progress_bytes = bytes_read

            if expected_sha256:
                actual = hasher.hexdigest()
                if actual != expected_sha256:
                    raise ValueError(
                        f'SHA256 mismatch: expected {expected_sha256}, got {actual}'
                    )

            if not zipfile.is_zipfile(tmp_path):
                raise ValueError('Downloaded file is not a valid zip')

            dataset_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(tmp_path, 'r') as zf:
                zf.extractall(str(dataset_dir))

            manifest_path = dataset_dir / 'dataset_manifest.json'
            if not manifest_path.exists():
                for p in dataset_dir.rglob('dataset_manifest.json'):
                    manifest_path = p
                    break

            if not manifest_path.exists():
                raise ValueError('Downloaded dataset has no dataset_manifest.json')

            if manifest_path.parent != dataset_dir:
                for item in manifest_path.parent.iterdir():
                    dest = dataset_dir / item.name
                    if not dest.exists():
                        shutil.move(str(item), str(dest))

            marker_data = {
                'sha256': hasher.hexdigest(),
                'downloaded_at': datetime.utcnow().isoformat(),
                'download_url': download_url,
            }
            with open(dataset_dir / '.download_complete', 'w') as f:
                json.dump(marker_data, f, indent=2)

            manifest = DatasetManifest.from_file(str(dataset_dir / 'dataset_manifest.json'))
            self._datasets[name] = manifest

            job.status = 'completed'
            job.completed_at = datetime.utcnow().isoformat()

        except Exception as e:
            job.status = 'failed'
            job.error = str(e)
            job.completed_at = datetime.utcnow().isoformat()
            if dataset_dir.exists() and not marker_path.exists():
                shutil.rmtree(dataset_dir, ignore_errors=True)

        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.unlink(tmp_file)
                except OSError:
                    pass

    def get_download_status(self, download_id: str) -> Optional[Dict]:
        job = self._downloads.get(download_id)
        if job:
            return job.get_summary()
        return None

    def list_downloads(self) -> List[Dict]:
        return [d.get_summary() for d in self._downloads.values()]

    # === Delete ===

    def delete_dataset(self, name: str) -> Dict:
        dataset_dir = self.datasets_dir / name
        if not dataset_dir.exists():
            return {
                'error': 'NOT_FOUND',
                'message': f'Dataset "{name}" not found',
            }

        shutil.rmtree(dataset_dir)
        self._datasets.pop(name, None)

        return {'deleted': True, 'name': name}

    # === Upload (custom datasets) ===

    def upload_dataset(self, zip_path: str, name: str = None,
                       display_name: str = None) -> Dict:
        if not zipfile.is_zipfile(zip_path):
            return {'error': 'INVALID_ZIP', 'message': 'Uploaded file is not a valid zip'}

        if not name:
            zip_name = Path(zip_path).stem
            name = self._slugify(zip_name)

        if name in self._datasets:
            return {
                'error': 'ALREADY_EXISTS',
                'message': f'Dataset "{name}" already exists',
            }

        if not display_name:
            display_name = name.replace('_', ' ').replace('-', ' ').title()

        dataset_dir = self.datasets_dir / name
        tmp_dir = None

        try:
            tmp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_dir)

            extracted = Path(tmp_dir)
            subdirs = [d for d in extracted.iterdir() if d.is_dir() and not d.name.startswith('__')]
            if len(subdirs) == 1 and not any(extracted.glob('*.mp4')):
                extracted = subdirs[0]

            structure = self.detect_structure(str(extracted))

            if structure['structure_type'] == 'explicit_manifest':
                dataset_dir.mkdir(parents=True, exist_ok=True)
                for item in extracted.iterdir():
                    dest = dataset_dir / item.name
                    shutil.move(str(item), str(dest))
                manifest = DatasetManifest.from_file(str(dataset_dir / 'dataset_manifest.json'))
            else:
                manifest = self.generate_manifest(str(extracted), name, display_name, structure)
                dataset_dir.mkdir(parents=True, exist_ok=True)
                for item in extracted.iterdir():
                    dest = dataset_dir / item.name
                    if item.is_dir():
                        shutil.copytree(str(item), str(dest))
                    else:
                        shutil.copy2(str(item), str(dest))
                manifest.to_file(str(dataset_dir / 'dataset_manifest.json'))

            with open(dataset_dir / '.user_uploaded', 'w') as f:
                json.dump({'uploaded_at': datetime.utcnow().isoformat()}, f)

            self._datasets[name] = manifest

            return {
                'name': name,
                'status': 'user_uploaded',
                'detected_structure': structure['structure_type'],
                'ground_truth_type': manifest.ground_truth_type,
                'total_files': len(manifest.files),
                'labeled_files': len(manifest.get_labeled_files()),
                'total_fall': manifest.statistics.get('total_fall', 0),
                'total_adl': manifest.statistics.get('total_adl', 0),
                'manifest': manifest.to_dict(),
            }

        except Exception as e:
            if dataset_dir.exists():
                shutil.rmtree(dataset_dir, ignore_errors=True)
            return {'error': 'UPLOAD_FAILED', 'message': str(e)}

        finally:
            if tmp_dir and os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def detect_structure(self, extracted_path: str) -> Dict:
        path = Path(extracted_path)

        manifest_path = path / 'dataset_manifest.json'
        if manifest_path.exists():
            return {
                'structure_type': 'explicit_manifest',
                'ground_truth_type': 'unknown',
                'label_folders': [],
                'video_count': 0,
                'annotation_count': 0,
            }

        subdirs = [d for d in path.iterdir()
                    if d.is_dir() and not d.name.startswith('.') and d.name != '__MACOSX']

        videos_dir = path / 'videos'
        if videos_dir.exists() and videos_dir.is_dir():
            subdirs = [d for d in videos_dir.iterdir()
                       if d.is_dir() and not d.name.startswith('.')]

        label_folders = []
        video_count = 0
        for sd in subdirs:
            vids = [f for f in sd.rglob('*') if f.suffix.lower() in VIDEO_EXTENSIONS]
            if vids:
                label_folders.append(sd.name)
                video_count += len(vids)

        if not label_folders:
            all_videos = [f for f in path.rglob('*')
                          if f.suffix.lower() in VIDEO_EXTENSIONS
                          and not f.name.startswith('.') and '__MACOSX' not in str(f)]
            video_count = len(all_videos)

        annotations_dir = path / 'annotations'
        annotation_count = 0
        if annotations_dir.exists():
            annotation_count = len([f for f in annotations_dir.rglob('*.csv')])

        if label_folders:
            gt_type = 'video_level'
            if annotation_count > 0:
                gt_type = 'frame_level'
            return {
                'structure_type': 'folder_labels' if annotation_count == 0 else 'with_annotations',
                'ground_truth_type': gt_type,
                'label_folders': label_folders,
                'video_count': video_count,
                'annotation_count': annotation_count,
            }

        if annotation_count > 0:
            return {
                'structure_type': 'with_annotations',
                'ground_truth_type': 'frame_level',
                'label_folders': [],
                'video_count': video_count,
                'annotation_count': annotation_count,
            }

        return {
            'structure_type': 'flat_unlabeled',
            'ground_truth_type': 'none',
            'label_folders': [],
            'video_count': video_count,
            'annotation_count': 0,
        }

    def generate_manifest(self, extracted_path: str, name: str,
                          display_name: str, structure: Dict) -> DatasetManifest:
        path = Path(extracted_path)
        files = []
        gt_type = structure['ground_truth_type']
        label_folders = structure['label_folders']

        videos_root = path / 'videos' if (path / 'videos').exists() else path

        if label_folders:
            search_root = path / 'videos' if (path / 'videos').exists() else path
            for folder_name in label_folders:
                folder_path = search_root / folder_name
                if not folder_path.exists():
                    continue

                label = self._folder_to_label(folder_name)
                fall_gt = self._label_to_ground_truth(label)

                for vid in sorted(folder_path.rglob('*')):
                    if vid.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    if vid.name.startswith('.') or '__MACOSX' in str(vid):
                        continue

                    rel = vid.relative_to(path)
                    annotation_path = None
                    if structure['annotation_count'] > 0:
                        ann_name = vid.stem + '.csv'
                        ann_path = path / 'annotations' / ann_name
                        if ann_path.exists():
                            annotation_path = str(ann_path.relative_to(path))

                    probe = self._probe_video(str(vid))

                    files.append(DatasetFile(
                        filename=vid.name,
                        relative_path=str(rel),
                        label=label,
                        fall_detected_ground_truth=fall_gt,
                        annotations_path=annotation_path,
                        size_bytes=vid.stat().st_size,
                        duration_seconds=probe.get('duration_seconds'),
                        resolution=probe.get('resolution'),
                        fps=probe.get('fps'),
                    ))
        else:
            for vid in sorted(path.rglob('*')):
                if vid.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                if vid.name.startswith('.') or '__MACOSX' in str(vid):
                    continue

                rel = vid.relative_to(path)
                files.append(DatasetFile(
                    filename=vid.name,
                    relative_path=str(rel),
                    label='UNLABELED',
                    fall_detected_ground_truth=None,
                    size_bytes=vid.stat().st_size,
                    duration_seconds=None,
                    resolution=None,
                    fps=None,
                ))

        label_map = {'FALL': True, 'ADL': False}

        manifest = DatasetManifest(
            name=name,
            display_name=display_name,
            version='1.0.0',
            description=f'Dataset with {len(files)} files',
            input_type='video',
            ground_truth_type=gt_type,
            files=files,
            statistics={},
            label_map=label_map,
            total_size_mb=round(sum(f.size_bytes for f in files) / (1024 * 1024), 1),
        )
        manifest.recalculate_statistics()
        return manifest

    # === Labeling ===

    def label_file(self, dataset_name: str, filename: str, label: str) -> Dict:
        manifest = self._datasets.get(dataset_name)
        if not manifest:
            return {'error': 'NOT_FOUND', 'message': f'Dataset "{dataset_name}" not found'}

        label = label.upper()
        if label not in ('FALL', 'ADL', 'UNLABELED'):
            return {'error': 'INVALID_LABEL', 'message': f'Label must be FALL, ADL, or UNLABELED'}

        for f in manifest.files:
            if f.filename == filename:
                f.label = label
                f.fall_detected_ground_truth = self._label_to_ground_truth(label)
                manifest.recalculate_statistics()

                manifest_path = self.datasets_dir / dataset_name / 'dataset_manifest.json'
                manifest.to_file(str(manifest_path))

                return f.to_dict()

        return {'error': 'FILE_NOT_FOUND', 'message': f'File "{filename}" not found in dataset'}

    def bulk_label(self, dataset_name: str, labels: Dict[str, str]) -> Dict:
        manifest = self._datasets.get(dataset_name)
        if not manifest:
            return {'error': 'NOT_FOUND', 'message': f'Dataset "{dataset_name}" not found'}

        updated = 0
        errors = []
        file_map = {f.filename: f for f in manifest.files}

        for filename, label in labels.items():
            label = label.upper()
            if label not in ('FALL', 'ADL', 'UNLABELED'):
                errors.append(f'Invalid label "{label}" for "{filename}"')
                continue
            f = file_map.get(filename)
            if not f:
                errors.append(f'File "{filename}" not found')
                continue
            f.label = label
            f.fall_detected_ground_truth = self._label_to_ground_truth(label)
            updated += 1

        manifest.recalculate_statistics()
        manifest_path = self.datasets_dir / dataset_name / 'dataset_manifest.json'
        manifest.to_file(str(manifest_path))

        result = {
            'updated': updated,
            'statistics': manifest.statistics,
        }
        if errors:
            result['errors'] = errors
        return result

    # === File access ===

    def get_file_path(self, dataset_name: str, filename: str) -> Optional[str]:
        manifest = self._datasets.get(dataset_name)
        if not manifest:
            return None

        for f in manifest.files:
            if f.filename == filename:
                full_path = self.datasets_dir / dataset_name / f.relative_path
                if full_path.exists():
                    return str(full_path)
                return None
        return None

    def prepare_for_evaluation(self, eval_id: str, dataset_name: str,
                               selected_files: List[str] = None) -> str:
        manifest = self._datasets.get(dataset_name)
        if not manifest:
            raise ValueError(f'Dataset "{dataset_name}" not found')

        eval_dir = self.datasets_shared_dir / eval_id
        eval_dir.mkdir(parents=True, exist_ok=True)

        if selected_files:
            file_map = {f.filename: f for f in manifest.files}
            files_to_copy = []
            for fn in selected_files:
                df = file_map.get(fn)
                if not df:
                    raise ValueError(f'File "{fn}" not found in dataset "{dataset_name}"')
                files_to_copy.append(df)
        else:
            files_to_copy = list(manifest.files)

        dataset_root = self.datasets_dir / dataset_name
        for df in files_to_copy:
            src = dataset_root / df.relative_path
            dest = eval_dir / df.filename
            if src.exists() and not dest.exists():
                shutil.copy2(str(src), str(dest))

        return f'/shared/datasets/{eval_id}'

    def copy_to_uploads(self, dataset_name: str, filenames: List[str]) -> Dict:
        manifest = self._datasets.get(dataset_name)
        if not manifest:
            return {'error': 'NOT_FOUND', 'message': f'Dataset "{dataset_name}" not found'}

        uploads_dir = self.shared_dir / 'uploads'
        uploads_dir.mkdir(parents=True, exist_ok=True)

        file_map = {f.filename: f for f in manifest.files}
        dataset_root = self.datasets_dir / dataset_name
        copied = []
        skipped = []
        errors = []

        for fn in filenames:
            df = file_map.get(fn)
            if not df:
                errors.append({'filename': fn, 'reason': 'not found in dataset'})
                continue

            src = dataset_root / df.relative_path
            dest = uploads_dir / df.filename

            if dest.exists():
                skipped.append(fn)
                continue

            if not src.exists():
                errors.append({'filename': fn, 'reason': 'source file missing'})
                continue

            shutil.copy2(str(src), str(dest))
            copied.append(fn)

        result = {
            'copied': copied,
            'skipped': skipped,
            'total_copied': len(copied),
            'total_skipped': len(skipped),
        }
        if errors:
            result['errors'] = errors
        return result

    def cleanup_evaluation(self, eval_id: str) -> bool:
        eval_dir = self.datasets_shared_dir / eval_id
        if eval_dir.exists():
            shutil.rmtree(eval_dir, ignore_errors=True)
            return True
        return False

    # === Helpers ===

    @staticmethod
    def _slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s-]+', '_', text)
        text = re.sub(r'_+', '_', text)
        return text.strip('_')

    @staticmethod
    def _folder_to_label(folder_name: str) -> str:
        lower = folder_name.lower()
        if lower in FALL_FOLDER_NAMES or 'fall' in lower:
            return 'FALL'
        if lower in ADL_FOLDER_NAMES or any(kw in lower for kw in ('adl', 'normal', 'daily')):
            return 'ADL'
        return 'UNLABELED'

    @staticmethod
    def _label_to_ground_truth(label: str) -> Optional[bool]:
        if label == 'FALL':
            return True
        if label == 'ADL':
            return False
        return None

    @staticmethod
    def _probe_video(path: str) -> Dict:
        try:
            import cv2
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return {}
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            duration = frames / fps if fps > 0 else 0
            return {
                'fps': round(fps, 2),
                'duration_seconds': round(duration, 2),
                'resolution': f'{w}x{h}',
            }
        except Exception:
            return {}
