
import hashlib
import json
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path


def compute_sha256(filepath):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(64 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def pack_detector(detector_dir, archive_name, extract_to, output_dir):
    detector_path = Path(detector_dir)

    if extract_to == '.':
        target = detector_path / 'models'
        if not target.exists():
            return None, None
        archive_path = output_dir / archive_name
        with tarfile.open(archive_path, 'w:gz') as tar:
            tar.add(str(target), arcname='models')
    else:
        target = detector_path / extract_to
        if not target.exists():
            return None, None
        archive_path = output_dir / archive_name
        with tarfile.open(archive_path, 'w:gz') as tar:
            tar.add(str(target), arcname=extract_to)

    sha256 = compute_sha256(archive_path)
    return archive_path, sha256


def write_marker(detector_dir, sha256, archive_name):
    marker_path = Path(detector_dir) / '.download_complete'
    marker_data = {
        'sha256': sha256,
        'downloaded_at': datetime.utcnow().isoformat(),
        'version': 'v1.0',
        'archive_name': archive_name
    }
    with open(marker_path, 'w') as f:
        json.dump(marker_data, f, indent=2)
    return marker_path


def main():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    detectors_dir = project_root / 'detectors'
    output_dir = project_root / 'archives'
    output_dir.mkdir(exist_ok=True)

    if not detectors_dir.exists():
        print(f'Error: detectors/ not found at {detectors_dir}')
        sys.exit(1)

    checksums = {}
    manifest_updates = {}
    results = []

    for entry in sorted(detectors_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith('_'):
            continue

        manifest_path = entry / 'manifest.json'
        if not manifest_path.exists():
            continue

        with open(manifest_path) as f:
            manifest = json.load(f)

        download_config = manifest.get('download')
        if not download_config:
            continue

        archive_name = download_config['archive_name']
        extract_to = download_config.get('extract_to', 'repo')
        detector_name = entry.name

        print(f'Packing {detector_name}...')
        archive_path, sha256 = pack_detector(
            str(entry), archive_name, extract_to, output_dir
        )

        if not archive_path:
            print(f'  SKIP: no content found ({extract_to}/ missing)')
            continue

        size_bytes = archive_path.stat().st_size
        size_mb = round(size_bytes / (1024 * 1024), 1)

        checksums[archive_name] = sha256
        manifest_updates[detector_name] = {
            'sha256': sha256,
            'size_mb': size_mb
        }

        marker_path = write_marker(str(entry), sha256, archive_name)

        results.append({
            'detector': detector_name,
            'archive': archive_name,
            'size_mb': size_mb,
            'sha256': sha256
        })

        print(f'  -> {archive_name} ({size_mb} MB)')
        print(f'  -> SHA256: {sha256}')
        print(f'  -> Marker: {marker_path}')

    checksums_path = output_dir / 'checksums.json'
    with open(checksums_path, 'w') as f:
        json.dump(checksums, f, indent=2)

    updated_count = 0
    for detector_name, updates in manifest_updates.items():
        manifest_path = detectors_dir / detector_name / 'manifest.json'
        with open(manifest_path) as f:
            manifest = json.load(f)

        manifest['download']['sha256'] = updates['sha256']
        manifest['download']['size_mb'] = updates['size_mb']

        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=4)
            f.write('\n')

        updated_count += 1

    print(f'\n{"="*60}')
    print(f'Packed {len(results)} detector(s) into {output_dir}/')
    print(f'Updated {updated_count} manifest(s) with SHA256 values')
    print(f'Checksums written to {checksums_path}')
    print(f'\nSummary:')
    total_mb = 0
    for r in results:
        print(f'  {r["detector"]}: {r["size_mb"]} MB')
        total_mb += r['size_mb']
    print(f'  Total: {total_mb} MB')


if __name__ == '__main__':
    main()
