
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
        if id.startswith('b-'):
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
        if id.startswith('b-'):
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


class _noop_context:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def main():
    cli(obj={})


if __name__ == '__main__':
    main()
