
import os
import uuid
import zipfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Optional
from werkzeug.utils import secure_filename


class FileManager:

    def __init__(self, shared_dir: str = '/shared', uploads_subdir: str = 'uploads'):
        self.shared_dir = Path(shared_dir)
        self.uploads_dir = self.shared_dir / uploads_subdir
        self.batch_dir = self.shared_dir / 'batch'

        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.batch_dir.mkdir(parents=True, exist_ok=True)

    def save_uploaded_file(self, file_storage, prefix: str = '') -> Tuple[str, str]:
        original_filename = secure_filename(file_storage.filename)
        name, ext = os.path.splitext(original_filename)
        unique_filename = f'{prefix}{uuid.uuid4().hex[:8]}_{name}{ext}'

        file_path = self.uploads_dir / unique_filename
        file_storage.save(str(file_path))

        absolute_path = str(file_path)
        relative_path = f'/shared/uploads/{unique_filename}'

        return absolute_path, relative_path

    def extract_zip(self, zip_path: str, batch_id: str, input_type: str = 'video') -> List[str]:
        extract_dir = self.batch_dir / batch_id
        extract_dir.mkdir(parents=True, exist_ok=True)

        if not zipfile.is_zipfile(zip_path):
            raise ValueError(f'Invalid zip file: {zip_path}')

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            raise ValueError(f'Failed to extract zip: {str(e)}')

        if input_type == 'video':
            valid_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'}
        elif input_type == 'sensor_csv':
            valid_extensions = {'.csv'}
        else:
            raise ValueError(f'Invalid input_type: {input_type}')

        valid_files = []
        for file_path in extract_dir.rglob('*'):
            if file_path.is_file():
                ext = file_path.suffix.lower()
                if ext in valid_extensions:
                    if not file_path.name.startswith('.') and '__MACOSX' not in str(file_path):
                        valid_files.append(str(file_path))

        if not valid_files:
            raise ValueError(
                f'No valid {input_type} files found in zip. '
                f'Expected extensions: {", ".join(valid_extensions)}'
            )

        valid_files.sort()

        return valid_files

    def list_files(self) -> List[dict]:
        files = []
        for file_path in sorted(self.uploads_dir.iterdir()):
            if file_path.is_file() and not file_path.name.startswith('.'):
                stat = file_path.stat()
                uploaded_at = datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat()
                files.append({
                    'filename': file_path.name,
                    'size_bytes': stat.st_size,
                    'size_mb': round(stat.st_size / (1024 * 1024), 2),
                    'uploaded_at': uploaded_at
                })
        return files

    def get_file_info(self, file_path: str) -> dict:
        path = Path(file_path)
        if not path.exists():
            return {'error': 'File not found'}

        stat = path.stat()
        return {
            'filename': path.name,
            'size_bytes': stat.st_size,
            'size_mb': round(stat.st_size / (1024 * 1024), 2),
            'absolute_path': str(path),
            'exists': True
        }

    def delete_file(self, file_path: str) -> bool:
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                return True
            return False
        except Exception:
            return False

    def delete_batch_files(self, batch_id: str) -> bool:
        try:
            batch_path = self.batch_dir / batch_id
            if batch_path.exists():
                shutil.rmtree(batch_path)
                return True
            return False
        except Exception:
            return False

    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        import time

        deleted_count = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        for file_path in self.uploads_dir.glob('*'):
            if file_path.is_file():
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                    except Exception:
                        pass

        for batch_path in self.batch_dir.glob('*'):
            if batch_path.is_dir():
                dir_age = current_time - batch_path.stat().st_mtime
                if dir_age > max_age_seconds:
                    try:
                        shutil.rmtree(batch_path)
                        deleted_count += 1
                    except Exception:
                        pass

        return deleted_count

    def get_disk_usage(self) -> dict:
        total, used, free = shutil.disk_usage(self.shared_dir)

        return {
            'total_gb': round(total / (1024**3), 2),
            'used_gb': round(used / (1024**3), 2),
            'free_gb': round(free / (1024**3), 2),
            'percent_used': round((used / total) * 100, 1)
        }
