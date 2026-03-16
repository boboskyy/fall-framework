
import json
import os
import subprocess

import click

from cli import __version__
from cli.api_client import GatewayClient, GatewayError
from cli.constants import GATEWAY_URL
from cli.formatters import (
    console,
    format_detector_list,
    format_detector_detail,
    format_health_summary,
    format_detection_result,
    format_comparison_result,
    format_batch_status,
    format_job_list,
    format_file_list,
    format_status,
    print_error,
    print_success,
    print_info,
)


def _get_client(ctx):
    if 'client' not in ctx.obj:
        ctx.obj['client'] = GatewayClient(ctx.obj.get('gateway_url', GATEWAY_URL))
    return ctx.obj['client']


def _find_project_root():
    candidates = [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        os.getcwd(),
        '/media/sf_mag/fall-framework',
    ]
    for path in candidates:
        if os.path.exists(os.path.join(path, 'docker-compose.yml')):
            return path
    return None


def _read_service_name(detector_name):
    root = _find_project_root()
    if not root:
        return None

    manifest_path = os.path.join(root, 'detectors', detector_name, 'manifest.json')
    if not os.path.exists(manifest_path):
        return None

    with open(manifest_path) as f:
        manifest = json.load(f)

    return manifest.get('docker_service_name')


def _get_all_service_names():
    root = _find_project_root()
    if not root:
        return []

    detectors_dir = os.path.join(root, 'detectors')
    if not os.path.isdir(detectors_dir):
        return []

    services = []
    for entry in sorted(os.listdir(detectors_dir)):
        manifest_path = os.path.join(detectors_dir, entry, 'manifest.json')
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            svc = manifest.get('docker_service_name')
            if svc:
                services.append(svc)

    return services


def _run_compose(args, project_root=None):
    root = project_root or _find_project_root()
    if not root:
        print_error('Cannot find project root (docker-compose.yml).')
        raise SystemExit(1)

    cmd = ['docker', 'compose', '-f', os.path.join(root, 'docker-compose.yml')] + args
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        print_error('docker compose not found. Is Docker installed?')
        raise SystemExit(1)


def _detect_input_type(path):
    ext = os.path.splitext(path)[1].lower()
    video_exts = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.wmv', '.flv'}
    image_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
    sensor_exts = {'.csv', '.json', '.txt'}

    if ext in video_exts:
        return 'video'
    elif ext in image_exts:
        return 'image'
    elif ext in sensor_exts:
        return 'sensor_csv'
    return 'video'


def _parse_value(raw):
    try:
        val = float(raw)
        if val == int(val):
            return int(val)
        return val
    except (ValueError, OverflowError):
        return raw


def _parse_config(config_str):
    if not config_str:
        return {}
    config = {}
    for pair in config_str:
        if '=' not in pair:
            continue
        left, raw_value = pair.split('=', 1)
        value = _parse_value(raw_value)

        if ':' in left:
            detector, param = left.split(':', 1)
            detector = detector.strip()
            param = param.strip()
            if detector not in config:
                config[detector] = {}
            config[detector][param] = value
        else:
            config[left.strip()] = value
    return config


@click.group(invoke_without_command=True)
@click.option('--gateway', '-g', default=None, help='Gateway URL (default: http://localhost:3000)')
@click.version_option(version=__version__, prog_name='fallfw')
@click.pass_context
def cli(ctx, gateway):
    ctx.ensure_object(dict)
    if gateway:
        ctx.obj['gateway_url'] = gateway

    if ctx.invoked_subcommand is None:
        try:
            from cli.interactive import interactive_main
            client = _get_client(ctx)
            interactive_main(client)
        except ImportError as e:
            print_error(f'Interactive mode requires simple-term-menu: {e}')
            print_info('Install with: pip install simple-term-menu')
            print_info('Or use: python -m cli.main --help')


@cli.command('list')
@click.option('--refresh', '-r', is_flag=True, help='Refresh health status')
@click.pass_context
def list_detectors(ctx, refresh):
    client = _get_client(ctx)
    try:
        data = client.list_detectors(refresh=refresh)
        format_detector_list(data)
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('detector')
@click.pass_context
def info(ctx, detector):
    client = _get_client(ctx)
    try:
        data = client.get_detector(detector)
        format_detector_detail(data)
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('detector', required=False)
@click.pass_context
def params(ctx, detector):
    client = _get_client(ctx)
    try:
        if detector:
            _print_detector_params(client, detector)
        else:
            data = client.list_detectors()
            for d in data.get('detectors', []):
                _print_detector_params(client, d['name'])
    except GatewayError as e:
        print_error(str(e))


def _print_detector_params(client, name):
    from rich.table import Table
    from rich import box

    data = client.get_detector(name)
    manifest = data.get('manifest', {})
    schema = manifest.get('config_schema', {})

    if not schema:
        console.print(f'\n  [bold]{name}[/bold]: no configurable parameters')
        return

    table = Table(
        title=name,
        box=box.SIMPLE,
        show_lines=False
    )
    table.add_column('Parameter', style='bold')
    table.add_column('Type')
    table.add_column('Default', justify='right')
    table.add_column('Range', justify='right')
    table.add_column('Description')

    for param, spec in schema.items():
        ptype = spec.get('type', '?')
        default = str(spec.get('default', ''))
        pmin = spec.get('min')
        pmax = spec.get('max')
        range_str = f'{pmin}-{pmax}' if pmin is not None and pmax is not None else ''
        desc = spec.get('description', '')
        table.add_row(param, ptype, default, range_str, desc)

    console.print(table)
    console.print(f'  [dim]Usage: -c {name}:param=value[/dim]\n')


@cli.command()
@click.argument('detector', required=False)
@click.pass_context
def health(ctx, detector):
    client = _get_client(ctx)
    try:
        if detector:
            data = client.detector_health(detector)
            icon = '●' if data.get('status') == 'healthy' else '○'
            console.print(f'  {icon} {detector}: {data.get("status", "unknown")}')
        else:
            data = client.health()
            format_health_summary(data)
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('detector', required=False)
@click.option('--all', '-a', 'all_detectors', is_flag=True, help='Start all detectors')
@click.pass_context
def start(ctx, detector, all_detectors):
    if all_detectors:
        services = _get_all_service_names()
        if not services:
            print_error('No detector manifests found.')
            return
        print_info(f'Starting {len(services)} detector(s)...')
        _run_compose(['up', '-d'] + services)
    elif detector:
        if _needs_download(detector):
            print_error(f'Detector repo not downloaded. Run: fallfw download {detector}')
            return
        service = _read_service_name(detector)
        if not service:
            print_error(f'No manifest found for "{detector}".')
            return
        print_info(f'Starting {service}...')
        _run_compose(['up', '-d', service])
    else:
        print_error('Specify a detector name or use --all.')


@cli.command()
@click.argument('detector', required=False)
@click.option('--all', '-a', 'all_detectors', is_flag=True, help='Stop all detectors')
@click.pass_context
def stop(ctx, detector, all_detectors):
    if all_detectors:
        services = _get_all_service_names()
        if not services:
            print_error('No detector manifests found.')
            return
        print_info(f'Stopping {len(services)} detector(s)...')
        _run_compose(['stop'] + services)
    elif detector:
        service = _read_service_name(detector)
        if not service:
            print_error(f'No manifest found for "{detector}".')
            return
        print_info(f'Stopping {service}...')
        _run_compose(['stop', service])
    else:
        print_error('Specify a detector name or use --all.')


@cli.command()
@click.argument('detector', required=False)
@click.option('--all', '-a', 'all_detectors', is_flag=True, help='Build all images')
@click.option('--device', '-d', type=click.Choice(['cpu', 'gpu']), default='cpu',
              help='Build for cpu or gpu (default: cpu)')
@click.pass_context
def build(ctx, detector, all_detectors, device):
    build_args = ['--build-arg', f'DEVICE={device}'] if device == 'gpu' else []
    if all_detectors:
        services = _get_all_service_names()
        if not services:
            print_error('No detector manifests found.')
            return
        root = _find_project_root()
        missing = []
        if root:
            missing = [s for s in _get_downloadable_detectors(
                os.path.join(root, 'detectors')
            ) if _needs_download(s)]
        if missing:
            print_error(
                f'Not downloaded: {", ".join(missing)}\n'
                f'  Run: fallfw download --all'
            )
            return
        if device == 'gpu':
            print_info(f'Building {len(services)} image(s) with GPU support...')
        else:
            print_info(f'Building {len(services)} image(s)...')
        _run_compose(['build'] + build_args + services)
    elif detector:
        if _needs_download(detector):
            print_error(f'Detector repo not downloaded. Run: fallfw download {detector}')
            return
        service = _read_service_name(detector)
        if not service:
            print_error(f'No manifest found for "{detector}".')
            return
        if device == 'gpu':
            print_info(f'Building {service} with GPU support...')
        else:
            print_info(f'Building {service}...')
        _run_compose(['build'] + build_args + [service])
    else:
        print_error('Specify a detector name or use --all.')


@cli.command()
@click.argument('detector', required=False)
@click.option('--all', '-a', 'all_detectors', is_flag=True, help='Download all detector repos')
@click.option('--force', '-f', is_flag=True, help='Re-download even if already present')
@click.pass_context
def download(ctx, detector, all_detectors, force):
    root = _find_project_root()
    if not root:
        print_error('Cannot find project root (docker-compose.yml).')
        return

    base_url = _get_download_base_url(root)
    detectors_dir = os.path.join(root, 'detectors')

    if all_detectors:
        names = _get_downloadable_detectors(detectors_dir)
        if not names:
            print_error('No detectors with download config found.')
            return
        print_info(f'Downloading {len(names)} detector repo(s)...')
        for name in names:
            _download_one(detectors_dir, name, base_url, force)
    elif detector:
        if not _has_download_config(detectors_dir, detector):
            print_error(f'Detector "{detector}" has no download configuration.')
            return
        _download_one(detectors_dir, detector, base_url, force)
    else:
        print_error('Specify a detector name or use --all.')


def _get_download_base_url(root):
    url = os.environ.get('FALLFW_REPO_URL')
    if url:
        return url

    conf_path = os.path.join(root, '.fallfw.conf')
    if os.path.exists(conf_path):
        with open(conf_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('FALLFW_REPO_URL='):
                    return line.split('=', 1)[1].strip().strip('"\'')

    return 'https://github.com/boboskyy/fall-detector-repos/releases/download/v1.0/'


def _has_download_config(detectors_dir, detector_name):
    manifest_path = os.path.join(detectors_dir, detector_name, 'manifest.json')
    if not os.path.exists(manifest_path):
        return False
    with open(manifest_path) as f:
        manifest = json.load(f)
    return 'download' in manifest


def _get_downloadable_detectors(detectors_dir):
    names = []
    if not os.path.isdir(detectors_dir):
        return names
    for entry in sorted(os.listdir(detectors_dir)):
        if entry.startswith('_'):
            continue
        if _has_download_config(detectors_dir, entry):
            names.append(entry)
    return names


def _needs_download(detector_name):
    root = _find_project_root()
    if not root:
        return False
    detectors_dir = os.path.join(root, 'detectors')
    manifest_path = os.path.join(detectors_dir, detector_name, 'manifest.json')
    if not os.path.exists(manifest_path):
        return False
    with open(manifest_path) as f:
        manifest = json.load(f)
    if 'download' not in manifest:
        return False
    marker = os.path.join(detectors_dir, detector_name, '.download_complete')
    return not os.path.exists(marker)


def _download_one(detectors_dir, detector_name, base_url, force):
    import hashlib
    import tarfile
    import tempfile
    import urllib.request
    import urllib.error

    manifest_path = os.path.join(detectors_dir, detector_name, 'manifest.json')
    with open(manifest_path) as f:
        manifest = json.load(f)

    download_config = manifest['download']
    archive_name = download_config['archive_name']
    extract_to = download_config.get('extract_to', 'repo')
    expected_sha256 = download_config.get('sha256')
    size_mb = download_config.get('size_mb', 0)

    detector_dir = os.path.join(detectors_dir, detector_name)
    marker_path = os.path.join(detector_dir, '.download_complete')

    if not force and os.path.exists(marker_path):
        print_info(f'{detector_name}: already downloaded (use --force to re-download)')
        return

    url = base_url.rstrip('/') + '/' + archive_name
    console.print(f'  [bold]{detector_name}[/bold]: downloading ({size_mb} MB)...')

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=300) as response:
            content_length = response.headers.get('Content-Length')
            total = int(content_length) if content_length else size_mb * 1024 * 1024

            tmp_fd, tmp_path = tempfile.mkstemp(suffix='.tar.gz')
            os.close(tmp_fd)

            try:
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
                        if total > 0:
                            pct = min(100, round(bytes_read / total * 100))
                            mb = round(bytes_read / (1024 * 1024), 1)
                            print(f'\r    {mb} MB ({pct}%)', end='', flush=True)

                print()

                actual_sha256 = hasher.hexdigest()
                if expected_sha256 and actual_sha256 != expected_sha256:
                    print_error(
                        f'{detector_name}: SHA256 mismatch!\n'
                        f'    Expected: {expected_sha256}\n'
                        f'    Got:      {actual_sha256}'
                    )
                    return

                import shutil
                if extract_to != '.':
                    target = os.path.join(detector_dir, extract_to)
                    if os.path.exists(target):
                        shutil.rmtree(target)
                else:
                    models = os.path.join(detector_dir, 'models')
                    if os.path.exists(models):
                        shutil.rmtree(models)
                if os.path.exists(marker_path):
                    os.unlink(marker_path)

                with tarfile.open(tmp_path, 'r:gz') as tar:
                    tar.extractall(path=detector_dir, filter='data')

                marker_data = {
                    'sha256': actual_sha256,
                    'downloaded_at': __import__('datetime').datetime.utcnow().isoformat(),
                    'version': 'v1.0',
                    'archive_name': archive_name
                }
                with open(marker_path, 'w') as f:
                    json.dump(marker_data, f, indent=2)

                print_success(f'{detector_name}: downloaded and extracted')

            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

    except urllib.error.URLError as e:
        print_error(f'{detector_name}: download failed — {e}')
    except Exception as e:
        print_error(f'{detector_name}: {e}')


@cli.command()
@click.argument('detector')
@click.option('--follow', '-f', is_flag=True, help='Follow log output')
@click.pass_context
def logs(ctx, detector, follow):
    service = _read_service_name(detector)
    if not service:
        print_error(f'No manifest found for "{detector}".')
        return

    args = ['logs']
    if follow:
        args.append('-f')
    args.append(service)

    _run_compose(args)


@cli.command()
@click.argument('file_path')
@click.pass_context
def upload(ctx, file_path):
    client = _get_client(ctx)

    if not os.path.exists(file_path):
        print_error(f'File not found: {file_path}')
        return

    try:
        with console.status('Uploading...'):
            data = client.upload_file(file_path)
        print_success(f'Uploaded: {data.get("filename", "?")}')
        console.print(f'  Path: {data.get("input_path", "")}')
        console.print(f'  Size: {data.get("size_mb", 0):.1f} MB')
    except GatewayError as e:
        print_error(str(e))


@cli.command('files')
@click.pass_context
def list_files(ctx):
    client = _get_client(ctx)
    try:
        data = client.list_files()
        format_file_list(data)
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('file')
@click.option('--detector', '-d', required=True, help='Detector name')
@click.option('--type', '-t', 'input_type', default=None, help='Input type (video/image/sensor_csv)')
@click.option('--config', '-c', multiple=True, help='Config: key=value or detector:key=value')
@click.option('--label', '-l', default=None, help='Human-readable label for the job')
@click.option('--async', 'use_async', is_flag=True, help='Run asynchronously')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON')
@click.pass_context
def detect(ctx, file, detector, input_type, config, label, use_async, output_json):
    client = _get_client(ctx)
    parsed_config = _parse_config(config)
    input_type = input_type or _detect_input_type(file)

    try:
        input_path = file
        if not file.startswith('/shared/'):
            if not os.path.exists(file):
                print_error(f'File not found: {file}')
                return
            with console.status('Uploading...'):
                upload_result = client.upload_file(file)
            input_path = upload_result['input_path']
            print_info(f'Uploaded as {input_path}')

        if use_async:
            data = client.detect_async(input_path, detector, input_type, parsed_config, label=label)
            job_id = data.get('job_id', '?')
            print_success(f'Job submitted: {job_id}')
            print_info(f'Check status: python -m cli.main status {job_id}')
        else:
            with console.status(f'Running detection with {detector}...'):
                data = client.detect_sync(input_path, detector, input_type, parsed_config, label=label)
            format_detection_result(data, raw_json=output_json)
    except GatewayError as e:
        print_error(str(e))


@cli.command('detect-multi')
@click.argument('file')
@click.option('--detectors', '-d', required=True, help='Comma-separated detector names')
@click.option('--type', '-t', 'input_type', default=None, help='Input type')
@click.option('--config', '-c', multiple=True, help='Config: key=value (global) or detector:key=value (per-detector)')
@click.option('--label', '-l', default=None, help='Human-readable label for the job')
@click.option('--async', 'use_async', is_flag=True, help='Run asynchronously')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON')
@click.pass_context
def detect_multi(ctx, file, detectors, input_type, config, label, use_async, output_json):
    client = _get_client(ctx)
    detector_list = [d.strip() for d in detectors.split(',')]
    parsed_config = _parse_config(config)
    input_type = input_type or _detect_input_type(file)

    try:
        input_path = file
        if not file.startswith('/shared/'):
            if not os.path.exists(file):
                print_error(f'File not found: {file}')
                return
            with console.status('Uploading...'):
                upload_result = client.upload_file(file)
            input_path = upload_result['input_path']
            print_info(f'Uploaded as {input_path}')

        sync = not use_async
        with console.status(f'Running detection with {len(detector_list)} detector(s)...') if sync else _noop_context():
            data = client.detect_multi(input_path, detector_list, input_type, parsed_config, sync=sync, label=label)

        if use_async:
            job_id = data.get('job_id', '?')
            print_success(f'Job submitted: {job_id}')
            print_info(f'Check status: python -m cli.main status {job_id}')
        else:
            format_detection_result(data, raw_json=output_json)
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('file')
@click.option('--detectors', '-d', required=True, help='Comma-separated detector names (2+ required)')
@click.option('--type', '-t', 'input_type', default=None, help='Input type')
@click.option('--config', '-c', multiple=True, help='Config: key=value (global) or detector:key=value (per-detector)')
@click.option('--label', '-l', default=None, help='Human-readable label for the comparison')
@click.option('--async', 'use_async', is_flag=True, help='Run asynchronously')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON')
@click.pass_context
def compare(ctx, file, detectors, input_type, config, label, use_async, output_json):
    client = _get_client(ctx)
    detector_list = [d.strip() for d in detectors.split(',')]
    parsed_config = _parse_config(config)
    input_type = input_type or _detect_input_type(file)

    if len(detector_list) < 2:
        print_error('At least 2 detectors required for comparison.')
        return

    try:
        input_path = file
        if not file.startswith('/shared/'):
            if not os.path.exists(file):
                print_error(f'File not found: {file}')
                return
            with console.status('Uploading...'):
                upload_result = client.upload_file(file)
            input_path = upload_result['input_path']
            print_info(f'Uploaded as {input_path}')

        sync = not use_async
        if sync:
            with console.status(f'Comparing {len(detector_list)} detectors...'):
                data = client.compare(input_path, detector_list, input_type, parsed_config, sync=True, label=label)
            comp_id = data.get('comparison_id')
            if comp_id:
                full_result = client.get_comparison(comp_id)
                format_comparison_result(full_result, raw_json=output_json)
            else:
                format_comparison_result(data, raw_json=output_json)
        else:
            data = client.compare(input_path, detector_list, input_type, parsed_config, sync=False, label=label)
            comp_id = data.get('comparison_id', '?')
            print_success(f'Comparison submitted: {comp_id}')
            print_info(f'Check status: python -m cli.main status {comp_id}')
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('zip_file')
@click.option('--detectors', '-d', required=True, help='Comma-separated detector names')
@click.option('--type', '-t', 'input_type', default='video', help='Input type')
@click.option('--config', '-c', multiple=True, help='Config: key=value (global) or detector:key=value (per-detector)')
@click.option('--label', '-l', default=None, help='Human-readable label for the batch')
@click.option('--async', 'use_async', is_flag=True, help='Run asynchronously')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON')
@click.pass_context
def batch(ctx, zip_file, detectors, input_type, config, label, use_async, output_json):
    client = _get_client(ctx)
    detector_list = [d.strip() for d in detectors.split(',')]
    parsed_config = _parse_config(config)

    try:
        zip_path = zip_file
        if not zip_file.startswith('/shared/'):
            if not os.path.exists(zip_file):
                print_error(f'File not found: {zip_file}')
                return
            with console.status('Uploading zip...'):
                upload_result = client.upload_file(zip_file)
            zip_path = upload_result['input_path']
            print_info(f'Uploaded as {zip_path}')

        sync = not use_async
        if sync:
            with console.status(f'Processing batch with {len(detector_list)} detector(s)...'):
                data = client.batch_detect(zip_path, detector_list, input_type, parsed_config, sync=True, label=label)
            batch_id = data.get('batch_id')
            if batch_id:
                results = client.get_batch_results(batch_id)
                format_batch_status(results, raw_json=output_json)
            else:
                format_batch_status(data, raw_json=output_json)
        else:
            data = client.batch_detect(zip_path, detector_list, input_type, parsed_config, sync=False, label=label)
            batch_id = data.get('batch_id', '?')
            print_success(f'Batch submitted: {batch_id}')
            print_info(f'Check status: python -m cli.main status {batch_id}')
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('id')
@click.pass_context
def status(ctx, id):
    client = _get_client(ctx)
    try:
        if id.startswith('eval-'):
            data = client._get(f'/api/v1/evaluate/{id}/status')
            format_status(data)
            return
        elif id.startswith('b-'):
            data = client.get_batch_status(id)
        elif id.startswith('c-'):
            data = client.get_comparison(id)
        else:
            data = client.get_job(id)
        format_status(data)
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('id')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON')
@click.pass_context
def result(ctx, id, output_json):
    client = _get_client(ctx)
    try:
        if id.startswith('eval-'):
            data = client._get(f'/api/v1/evaluate/{id}/results')
            if output_json:
                console.print_json(data=data)
            else:
                _format_evaluation_result(data)
            return
        elif id.startswith('b-'):
            data = client.get_batch_results(id)
            format_batch_status(data, raw_json=output_json)
        elif id.startswith('c-'):
            data = client.get_comparison(id)
            format_comparison_result(data, raw_json=output_json)
        else:
            data = client.get_job_results(id)
            format_detection_result(data, raw_json=output_json)
    except GatewayError as e:
        print_error(str(e))


@cli.command()
@click.argument('id')
@click.argument('label_text')
@click.pass_context
def label(ctx, id, label_text):
    client = _get_client(ctx)
    try:
        data = client.set_label(id, label_text)
        print_success(f'Label set: {data.get("id")} → "{data.get("label")}"')
    except GatewayError as e:
        print_error(str(e))


# === Dataset subgroup ===

@cli.group()
@click.pass_context
def dataset(ctx):
    """Manage datasets for evaluation."""
    pass


@dataset.command('list')
@click.option('--status', '-s', default=None, help='Filter by status (available/downloaded/user_uploaded)')
@click.pass_context
def dataset_list(ctx, status):
    """List all datasets."""
    client = _get_client(ctx)
    try:
        data = client._get('/api/v1/datasets')
        datasets = data.get('datasets', [])
        if status:
            datasets = [d for d in datasets if d.get('status') == status]

        from rich.table import Table
        from rich import box
        table = Table(box=box.SIMPLE, show_lines=False)
        table.add_column('Name', style='bold')
        table.add_column('Status')
        table.add_column('GT Type')
        table.add_column('Files', justify='right')
        table.add_column('FALL', justify='right')
        table.add_column('ADL', justify='right')
        table.add_column('Size', justify='right')

        for ds in datasets:
            st = ds.get('status', '')
            color = {'downloaded': 'green', 'user_uploaded': 'cyan',
                     'available': 'yellow', 'downloading': 'blue'}.get(st, 'white')
            size = f'{ds.get("size_mb", 0)} MB' if ds.get('size_mb') else '?'
            table.add_row(
                ds.get('name', ''),
                f'[{color}]{st}[/{color}]',
                ds.get('ground_truth_type', ''),
                str(ds.get('total_files', 0)),
                str(ds.get('total_fall', 0)),
                str(ds.get('total_adl', 0)),
                size,
            )

        console.print(table)
    except GatewayError as e:
        print_error(str(e))


@dataset.command('info')
@click.argument('name')
@click.pass_context
def dataset_info(ctx, name):
    """Show dataset details."""
    client = _get_client(ctx)
    try:
        data = client._get(f'/api/v1/datasets/{name}')
        console.print_json(data=data)
    except GatewayError as e:
        print_error(str(e))


@dataset.command('files')
@click.argument('name')
@click.option('--label', '-l', default=None, help='Filter by label (FALL/ADL/UNLABELED)')
@click.pass_context
def dataset_files(ctx, name, label):
    """List files in a dataset."""
    client = _get_client(ctx)
    try:
        params = {}
        if label:
            params['label'] = label
        data = client._get(f'/api/v1/datasets/{name}/files', params=params)

        from rich.table import Table
        from rich import box
        table = Table(title=f'Dataset: {name}', box=box.SIMPLE)
        table.add_column('Filename', style='bold')
        table.add_column('Label')
        table.add_column('GT')
        table.add_column('Duration', justify='right')
        table.add_column('Resolution')
        table.add_column('Size', justify='right')

        for f in data.get('files', []):
            lbl = f.get('label', '')
            color = {'FALL': 'red', 'ADL': 'green', 'UNLABELED': 'dim'}.get(lbl, 'white')
            gt = 'Y' if f.get('fall_detected_ground_truth') else ('N' if f.get('fall_detected_ground_truth') is False else '?')
            dur = f'{f["duration_seconds"]:.1f}s' if f.get('duration_seconds') else '?'
            size = f'{f.get("size_bytes", 0) / 1024 / 1024:.1f} MB'
            table.add_row(
                f.get('filename', ''),
                f'[{color}]{lbl}[/{color}]',
                gt, dur,
                f.get('resolution', '?'),
                size,
            )

        console.print(table)
        pag = data.get('pagination', {})
        if pag.get('total_pages', 1) > 1:
            console.print(f'  Page {pag["page"]}/{pag["total_pages"]}')
    except GatewayError as e:
        print_error(str(e))


@dataset.command('download')
@click.argument('name')
@click.pass_context
def dataset_download(ctx, name):
    """Download a dataset from the registry."""
    client = _get_client(ctx)
    try:
        data = client._post(f'/api/v1/datasets/{name}/download')
        if data.get('error'):
            print_error(data.get('message', data['error']))
        else:
            print_success(f'Download started for "{name}"')
            dl_id = data.get('download_id')
            if dl_id:
                print_info(f'Download ID: {dl_id}')
    except GatewayError as e:
        print_error(str(e))


@dataset.command('delete')
@click.argument('name')
@click.confirmation_option(prompt='Are you sure you want to delete this dataset?')
@click.pass_context
def dataset_delete(ctx, name):
    """Delete a dataset."""
    client = _get_client(ctx)
    try:
        data = client._delete(f'/api/v1/datasets/{name}')
        if data.get('deleted'):
            print_success(f'Dataset "{name}" deleted')
        else:
            print_error(data.get('message', 'Delete failed'))
    except GatewayError as e:
        print_error(str(e))


@dataset.command('upload')
@click.argument('zip_path')
@click.option('--name', '-n', default=None, help='Dataset name (auto-generated if omitted)')
@click.pass_context
def dataset_upload(ctx, zip_path, name):
    """Upload a custom dataset zip."""
    client = _get_client(ctx)
    if not os.path.exists(zip_path):
        print_error(f'File not found: {zip_path}')
        return
    try:
        import requests as req_lib
        url = f'{client.base_url}/api/v1/datasets/upload'
        with open(zip_path, 'rb') as f:
            files = {'file': (os.path.basename(zip_path), f)}
            form_data = {}
            if name:
                form_data['name'] = name
            with console.status('Uploading dataset...'):
                resp = req_lib.post(url, files=files, data=form_data, timeout=600)
        data = resp.json()
        if resp.status_code >= 400:
            print_error(data.get('message', 'Upload failed'))
        else:
            print_success(f'Dataset uploaded: {data.get("name", "?")}')
            console.print(f'  Structure: {data.get("detected_structure", "?")}')
            console.print(f'  Ground truth: {data.get("ground_truth_type", "?")}')
            console.print(f'  Files: {data.get("total_files", 0)} ({data.get("total_fall", 0)} FALL, {data.get("total_adl", 0)} ADL)')
    except Exception as e:
        print_error(str(e))


@dataset.command('refresh')
@click.pass_context
def dataset_refresh(ctx):
    """Refresh dataset registry from remote."""
    client = _get_client(ctx)
    try:
        data = client._post('/api/v1/datasets/refresh-registry')
        avail = data.get('available', [])
        downloaded = data.get('downloaded', [])
        print_success(f'Registry refreshed: {len(avail)} available, {len(downloaded)} downloaded')
    except GatewayError as e:
        print_error(str(e))


@dataset.command('label')
@click.argument('name')
@click.argument('filename')
@click.argument('label_value', type=click.Choice(['FALL', 'ADL', 'UNLABELED']))
@click.pass_context
def dataset_label(ctx, name, filename, label_value):
    """Label a file in a dataset."""
    client = _get_client(ctx)
    try:
        data = client._patch(f'/api/v1/datasets/{name}/files/{filename}',
                             json={'label': label_value})
        if data.get('error'):
            print_error(data.get('message', data['error']))
        else:
            print_success(f'{filename} → {label_value}')
    except GatewayError as e:
        print_error(str(e))


# === Evaluation commands (flat, matching existing pattern) ===

@cli.command('evaluate')
@click.argument('dataset_name')
@click.option('--detectors', '-d', required=True, help='Comma-separated detector names')
@click.option('--files', '-f', 'selected_files', default=None, help='Comma-separated filenames (default: all)')
@click.option('--config', '-c', multiple=True, help='Config: key=value or detector:key=value')
@click.option('--min-fall-frames', default=1, type=int, help='Min fall frames for verdict (default: 1)')
@click.option('--min-fall-percentage', default=0.0, type=float, help='Min fall percentage for verdict (default: 0.0)')
@click.option('--sync', is_flag=True, help='Wait for completion')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON')
@click.pass_context
def evaluate(ctx, dataset_name, detectors, selected_files, config,
             min_fall_frames, min_fall_percentage, sync, output_json):
    """Evaluate a dataset against detectors."""
    client = _get_client(ctx)
    detector_list = [d.strip() for d in detectors.split(',')]
    parsed_config = _parse_config(config)
    files_list = [f.strip() for f in selected_files.split(',')] if selected_files else None

    body = {
        'dataset': dataset_name,
        'detectors': detector_list,
        'selected_files': files_list,
        'config': parsed_config if parsed_config else None,
        'verdict_config': {
            'min_fall_frames': min_fall_frames,
            'min_fall_percentage': min_fall_percentage,
        },
        'sync': sync,
    }

    try:
        if sync:
            with console.status(f'Evaluating {dataset_name} with {len(detector_list)} detector(s)...'):
                data = client._post('/api/v1/evaluate', json=body)
            if output_json:
                console.print_json(data=data)
            else:
                _format_evaluation_result(data)
        else:
            data = client._post('/api/v1/evaluate', json=body)
            if data.get('error'):
                print_error(data.get('message', data['error']))
            else:
                eval_id = data.get('eval_id', '?')
                print_success(f'Evaluation started: {eval_id}')
                print_info(f'Tasks: {data.get("total_tasks", 0)}')
                print_info(f'Check: fallfw evaluate-status {eval_id}')
    except GatewayError as e:
        print_error(str(e))


@cli.command('evaluate-status')
@click.argument('eval_id')
@click.pass_context
def evaluate_status(ctx, eval_id):
    """Check evaluation progress."""
    client = _get_client(ctx)
    try:
        data = client._get(f'/api/v1/evaluate/{eval_id}/status')
        if data.get('error'):
            print_error(data.get('message', data['error']))
            return

        st = data.get('status', 'unknown')
        total = data.get('total_tasks', 0)
        completed = data.get('completed_tasks', 0)
        failed = data.get('failed_tasks', 0)
        pct = data.get('progress_pct', 0)

        icon = {'completed': '[green]●[/green]', 'running': '[blue]◐[/blue]',
                'failed': '[red]●[/red]', 'partial': '[yellow]◑[/yellow]',
                'pending': '[dim]○[/dim]'}.get(st, '?')
        console.print(f'  {icon} {eval_id}: {st}')
        console.print(f'  Progress: {completed}/{total} ({pct}%) — {failed} failed')
    except GatewayError as e:
        print_error(str(e))


@cli.command('evaluate-result')
@click.argument('eval_id')
@click.option('--format', '-f', 'fmt', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def evaluate_result(ctx, eval_id, fmt):
    """View evaluation results."""
    client = _get_client(ctx)
    try:
        data = client._get(f'/api/v1/evaluate/{eval_id}/results')
        if data.get('error'):
            print_error(data.get('message', data['error']))
            return

        if fmt == 'json':
            console.print_json(data=data)
        else:
            _format_evaluation_result(data)
    except GatewayError as e:
        print_error(str(e))


@cli.command('evaluate-export')
@click.argument('eval_id')
@click.option('--format', '-f', 'fmt', type=click.Choice(['json', 'csv']), default='csv')
@click.option('--output', '-o', default=None, help='Output file path')
@click.pass_context
def evaluate_export(ctx, eval_id, fmt, output):
    """Export evaluation results."""
    client = _get_client(ctx)
    try:
        if fmt == 'csv':
            import requests as req_lib
            url = f'{client.base_url}/api/v1/evaluate/{eval_id}/export?format=csv'
            resp = req_lib.get(url, timeout=30)
            if resp.status_code != 200:
                print_error(f'Export failed: {resp.text}')
                return
            content = resp.text
        else:
            data = client._get(f'/api/v1/evaluate/{eval_id}/export', params={'format': 'json'})
            content = json.dumps(data, indent=2)

        if output:
            with open(output, 'w') as f:
                f.write(content)
            print_success(f'Exported to {output}')
        else:
            console.print(content)
    except GatewayError as e:
        print_error(str(e))


def _format_evaluation_result(data):
    """Format evaluation results as Rich tables."""
    from rich.table import Table
    from rich import box
    from rich.panel import Panel

    eval_id = data.get('eval_id', '?')
    dataset = data.get('dataset_name', '?')
    gt_type = data.get('ground_truth_type', '?')
    total_eval = data.get('total_files_evaluated', 0)
    total_ds = data.get('total_files_in_dataset', 0)

    console.print(Panel(
        f'Dataset: {dataset} | GT: {gt_type} | Files: {total_eval}/{total_ds}',
        title=f'Evaluation {eval_id}',
    ))

    # Detector summaries
    summaries = data.get('detector_summaries', [])
    if summaries:
        table = Table(title='Detector Metrics', box=box.SIMPLE)
        table.add_column('Detector', style='bold')
        table.add_column('Acc', justify='right')
        table.add_column('Prec', justify='right')
        table.add_column('Recall', justify='right')
        table.add_column('F1', justify='right')
        table.add_column('TP', justify='right')
        table.add_column('TN', justify='right')
        table.add_column('FP', justify='right')
        table.add_column('FN', justify='right')
        table.add_column('Avg Time', justify='right')

        for s in summaries:
            f1 = s.get('f1_score', 0)
            f1_color = 'green' if f1 >= 0.8 else ('yellow' if f1 >= 0.5 else 'red')
            table.add_row(
                s.get('detector_name', ''),
                f'{s.get("accuracy", 0):.3f}',
                f'{s.get("precision", 0):.3f}',
                f'{s.get("recall", 0):.3f}',
                f'[{f1_color}]{f1:.3f}[/{f1_color}]',
                str(s.get('true_positives', 0)),
                str(s.get('true_negatives', 0)),
                str(s.get('false_positives', 0)),
                str(s.get('false_negatives', 0)),
                f'{s.get("avg_processing_time_ms", 0):.0f}ms',
            )
        console.print(table)

    # Cross-detector agreement
    agreement = data.get('cross_detector_agreement')
    if agreement:
        console.print(f'\n  [bold]Cross-detector agreement:[/bold]')
        console.print(f'    Average: {agreement.get("average_agreement", 0):.3f}')
        console.print(f'    Best: {agreement.get("best_detector", "?")}')
        console.print(f'    Unanimous: {agreement.get("unanimous_files", 0)} files')
        console.print(f'    Split: {agreement.get("split_files", 0)} files')

    # Overall
    overall = data.get('overall_statistics')
    if overall:
        console.print(f'\n  [bold]Best detectors:[/bold]')
        console.print(f'    Accuracy: {overall.get("best_accuracy_detector", "?")}')
        console.print(f'    F1: {overall.get("best_f1_detector", "?")}')
        console.print(f'    Recall: {overall.get("best_recall_detector", "?")}')
        console.print(f'    Precision: {overall.get("best_precision_detector", "?")}')

    wall = data.get('total_wall_time_seconds')
    if wall:
        console.print(f'\n  Total time: {wall:.1f}s')


class _noop_context:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def main():
    cli(obj={})


if __name__ == '__main__':
    main()
