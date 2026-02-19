
import io
import json
import zipfile
import re
from pathlib import Path
from typing import Dict, Optional


PLACEHOLDERS = {
    '{{DETECTOR_NAME}}',
    '{{DETECTOR_CLASS}}',
    '{{DISPLAY_NAME}}',
    '{{SERVICE_NAME}}',
    '{{PORT}}',
    '{{CATEGORY}}',
    '{{INPUT_TYPE}}',
}

VALID_CATEGORIES = [
    'object_detection',
    'pose_estimation',
    'sensor_based',
    'hybrid',
]

VALID_INPUT_TYPES = [
    'video',
    'sensor_csv',
]


def _to_class_name(snake_name: str) -> str:
    parts = snake_name.split('_')
    pascal = ''.join(word.capitalize() for word in parts)
    if not pascal.endswith('Detector'):
        pascal += 'Detector'
    return pascal


def _to_service_name(detector_name: str) -> str:
    return detector_name.replace('_', '-')


def _find_next_port(detectors_dir: str) -> int:
    used_ports = set()
    detectors_path = Path(detectors_dir)

    if detectors_path.exists():
        for manifest_path in detectors_path.glob('*/manifest.json'):
            if manifest_path.parent.name == '_template':
                continue
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
                port = manifest.get('port')
                if port:
                    used_ports.add(int(port))
            except (json.JSONDecodeError, ValueError):
                continue

    port = 3001
    while port in used_ports:
        port += 1
    return port


def get_template_info(detectors_dir: str = '/detectors') -> Dict:
    next_port = _find_next_port(detectors_dir)

    template_dir = Path(detectors_dir) / '_template'
    files = []
    if template_dir.exists():
        for f in sorted(template_dir.iterdir()):
            if f.is_file():
                files.append({
                    'filename': f.name,
                    'size_bytes': f.stat().st_size,
                })

    return {
        'next_available_port': next_port,
        'template_files': files,
        'valid_categories': VALID_CATEGORIES,
        'valid_input_types': VALID_INPUT_TYPES,
        'parameters': {
            'name': {
                'required': True,
                'description': 'Detector directory name (snake_case, e.g. "my_fall_detector")',
                'pattern': '^[a-z][a-z0-9_]*$',
            },
            'category': {
                'required': False,
                'default': 'object_detection',
                'options': VALID_CATEGORIES,
            },
            'input_type': {
                'required': False,
                'default': 'video',
                'options': VALID_INPUT_TYPES,
            },
        },
    }


def generate_template_zip(
    detector_name: str,
    category: str = 'object_detection',
    input_type: str = 'video',
    detectors_dir: str = '/detectors',
) -> bytes:
    if not detector_name or not re.match(r'^[a-z][a-z0-9_]*$', detector_name):
        raise ValueError(
            f'Invalid detector name "{detector_name}". '
            'Must be snake_case (lowercase letters, digits, underscores), '
            'starting with a letter.'
        )

    if category not in VALID_CATEGORIES:
        raise ValueError(
            f'Invalid category "{category}". Must be one of: {", ".join(VALID_CATEGORIES)}'
        )

    if input_type not in VALID_INPUT_TYPES:
        raise ValueError(
            f'Invalid input_type "{input_type}". Must be one of: {", ".join(VALID_INPUT_TYPES)}'
        )

    existing_dir = Path(detectors_dir) / detector_name
    if existing_dir.exists():
        raise ValueError(
            f'Detector "{detector_name}" already exists at {existing_dir}'
        )

    port = _find_next_port(detectors_dir)
    class_name = _to_class_name(detector_name)
    service_name = _to_service_name(detector_name)
    display_name = detector_name.replace('_', ' ').title()

    replacements = {
        '{{DETECTOR_NAME}}': detector_name,
        '{{DETECTOR_CLASS}}': class_name,
        '{{DISPLAY_NAME}}': display_name,
        '{{SERVICE_NAME}}': service_name,
        '{{PORT}}': str(port),
        '{{CATEGORY}}': category,
        '{{INPUT_TYPE}}': input_type,
    }

    template_dir = Path(detectors_dir) / '_template'
    if not template_dir.exists():
        raise RuntimeError(f'Template directory not found: {template_dir}')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for template_file in sorted(template_dir.iterdir()):
            if not template_file.is_file():
                continue

            content = template_file.read_text(encoding='utf-8')

            for placeholder, value in replacements.items():
                content = content.replace(placeholder, value)

            zip_path = f'{detector_name}/{template_file.name}'
            zf.writestr(zip_path, content)

    return buf.getvalue()
