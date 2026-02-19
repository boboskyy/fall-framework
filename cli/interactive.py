
import os

from rich.console import Console

from cli.api_client import GatewayError
from cli.formatters import (
    format_detector_list,
    format_detector_detail,
    format_health_summary,
    format_detection_result,
    format_comparison_result,
    format_batch_status,
    format_job_list,
    format_file_list,
    print_error,
    print_success,
    print_info,
)

try:
    from simple_term_menu import TerminalMenu
except ImportError:
    TerminalMenu = None

console = Console()

BANNER = '''
[bold cyan]Fall Detection Framework[/bold cyan] [dim]v2.0[/dim]
'''


def interactive_main(client):
    if TerminalMenu is None:
        print_error(
            'Interactive mode requires simple-term-menu.\n'
            '  Install with: pip install simple-term-menu'
        )
        return

    console.print(BANNER)
    _main_menu(client)


def _main_menu(client):
    options = [
        'Detectors        — List, start, stop, build detectors',
        'Detect           — Run fall detection on a file',
        'Compare          — Compare multiple detectors',
        'Batch            — Process multiple files',
        'Jobs             — View job status & results',
        'Files            — Manage uploaded files',
        'Health           — System health check',
        'Exit',
    ]

    while True:
        menu = TerminalMenu(
            options,
            title='\nMain Menu',
            cursor_index=0,
            clear_screen=False,
        )
        choice = menu.show()

        if choice is None or choice == 7:
            console.print('[dim]Goodbye.[/dim]')
            break
        elif choice == 0:
            _detectors_menu(client)
        elif choice == 1:
            _detect_flow(client)
        elif choice == 2:
            _compare_flow(client)
        elif choice == 3:
            _batch_flow(client)
        elif choice == 4:
            _jobs_menu(client)
        elif choice == 5:
            _upload_menu(client)
        elif choice == 6:
            _health_flow(client)


def _detectors_menu(client):
    try:
        data = client.list_detectors(refresh=True)
    except GatewayError as e:
        print_error(str(e))
        return

    detectors = data.get('detectors', [])
    if not detectors:
        print_info('No detectors registered.')
        return

    format_detector_list(data)

    det_names = [f'{d["name"]}  [{d.get("container_status", "?")}]' for d in detectors]
    det_names.append('← Back')

    menu = TerminalMenu(det_names, title='\nSelect a detector')
    choice = menu.show()

    if choice is None or choice == len(det_names) - 1:
        return

    detector = detectors[choice]
    _detector_actions(client, detector['name'])


def _detector_actions(client, name):
    try:
        data = client.get_detector(name)
        format_detector_detail(data)
    except GatewayError as e:
        print_error(str(e))

    options = ['Info (refresh)', 'Start', 'Stop', 'Build', 'Logs', '← Back']
    menu = TerminalMenu(options, title=f'\n{name} — Actions')
    choice = menu.show()

    if choice is None or choice == 5:
        return
    elif choice == 0:
        try:
            data = client.get_detector(name)
            format_detector_detail(data)
        except GatewayError as e:
            print_error(str(e))
    elif choice == 1:
        _docker_action('start', name)
    elif choice == 2:
        _docker_action('stop', name)
    elif choice == 3:
        _docker_action('build', name)
    elif choice == 4:
        _docker_action('logs', name)


def _docker_action(action, detector_name):
    from cli.main import _read_service_name, _run_compose

    service = _read_service_name(detector_name)
    if not service:
        print_error(f'No manifest found for "{detector_name}".')
        return

    if action == 'start':
        print_info(f'Starting {service}...')
        _run_compose(['up', '-d', service])
    elif action == 'stop':
        print_info(f'Stopping {service}...')
        _run_compose(['stop', service])
    elif action == 'build':
        print_info(f'Building {service}...')
        _run_compose(['build', service])
    elif action == 'logs':
        _run_compose(['logs', '--tail', '50', service])


def _detect_flow(client):
    input_path = _select_file(client)
    if not input_path:
        return

    detector = _select_single_detector(client)
    if not detector:
        return

    config = _configure_detectors(client, [detector])

    input_type = _guess_input_type(input_path)
    console.print(f'\n  File: [bold]{input_path}[/bold]')
    console.print(f'  Detector: [bold]{detector}[/bold]')
    console.print(f'  Type: {input_type}')

    try:
        with console.status(f'Running detection with {detector}...'):
            data = client.detect_sync(input_path, detector, input_type, config=config)
        format_detection_result(data)
    except GatewayError as e:
        print_error(str(e))


def _compare_flow(client):
    input_path = _select_file(client)
    if not input_path:
        return

    detectors = _select_detectors(client, min_count=2)
    if not detectors:
        return

    config = _configure_detectors(client, detectors)

    input_type = _guess_input_type(input_path)
    console.print(f'\n  File: [bold]{input_path}[/bold]')
    console.print(f'  Detectors: [bold]{", ".join(detectors)}[/bold]')

    try:
        with console.status(f'Comparing {len(detectors)} detectors...'):
            data = client.compare(input_path, detectors, input_type, config=config, sync=True)

        comp_id = data.get('comparison_id')
        if comp_id:
            full_result = client.get_comparison(comp_id)
            format_comparison_result(full_result)
        else:
            format_comparison_result(data)
    except GatewayError as e:
        print_error(str(e))


def _batch_flow(client):
    console.print('\n  Enter the path to a zip file (local or /shared/ path):')
    zip_path = input('  > ').strip()

    if not zip_path:
        return

    if not zip_path.startswith('/shared/'):
        if not os.path.exists(zip_path):
            print_error(f'File not found: {zip_path}')
            return
        try:
            with console.status('Uploading zip...'):
                upload_result = client.upload_file(zip_path)
            zip_path = upload_result['input_path']
            print_info(f'Uploaded as {zip_path}')
        except GatewayError as e:
            print_error(str(e))
            return

    detectors = _select_detectors(client, min_count=1)
    if not detectors:
        return

    type_options = ['video', 'image', 'sensor_csv', '← Back']
    type_menu = TerminalMenu(type_options, title='\nInput type')
    type_choice = type_menu.show()
    if type_choice is None or type_choice == 3:
        return
    input_type = type_options[type_choice]

    config = _configure_detectors(client, detectors)

    console.print(f'\n  Zip: [bold]{zip_path}[/bold]')
    console.print(f'  Detectors: [bold]{", ".join(detectors)}[/bold]')
    console.print(f'  Type: {input_type}')

    try:
        with console.status(f'Processing batch...'):
            data = client.batch_detect(zip_path, detectors, input_type, config=config, sync=True)

        batch_id = data.get('batch_id')
        if batch_id:
            results = client.get_batch_results(batch_id)
            format_batch_status(results)
        else:
            format_batch_status(data)
    except GatewayError as e:
        print_error(str(e))


def _jobs_menu(client):
    try:
        data = client.list_jobs()
    except GatewayError as e:
        print_error(str(e))
        return

    jobs = data.get('jobs', [])
    if not jobs:
        print_info('No jobs found.')
        return

    format_job_list(data)

    try:
        comp_data = client.list_comparisons()
        comparisons = comp_data.get('comparisons', [])
    except GatewayError:
        comparisons = []

    try:
        batch_data = client.list_batches()
        batches = batch_data.get('batches', [])
    except GatewayError:
        batches = []

    items = []
    for j in jobs:
        jid = j.get('job_id', '?')[:12]
        jlabel = f'  "{j["label"]}"' if j.get('label') else ''
        items.append(f'Job  {jid}{jlabel}  [{j.get("status", "?")}]')

    for c in comparisons:
        cid = c.get('comparison_id', '?')[:12]
        clabel = f'  "{c["label"]}"' if c.get('label') else ''
        items.append(f'Comp {cid}{clabel}  [{c.get("status", "?")}]')

    for b in batches:
        bid = b.get('batch_id', '?')[:12]
        blabel = f'  "{b["label"]}"' if b.get('label') else ''
        items.append(f'Bat  {bid}{blabel}  [{b.get("status", "?")}]')

    items.append('← Back')

    menu = TerminalMenu(items, title='\nSelect to view details')
    choice = menu.show()

    if choice is None or choice == len(items) - 1:
        return

    if choice < len(jobs):
        job_id = jobs[choice].get('job_id')
        try:
            result = client.get_job_results(job_id)
            format_detection_result(result)
        except GatewayError as e:
            print_error(str(e))
    elif choice < len(jobs) + len(comparisons):
        idx = choice - len(jobs)
        comp_id = comparisons[idx].get('comparison_id')
        try:
            result = client.get_comparison(comp_id)
            format_comparison_result(result)
        except GatewayError as e:
            print_error(str(e))
    else:
        idx = choice - len(jobs) - len(comparisons)
        batch_id = batches[idx].get('batch_id')
        try:
            result = client.get_batch_results(batch_id)
            format_batch_status(result)
        except GatewayError as e:
            print_error(str(e))


def _upload_menu(client):
    options = ['List uploaded files', 'Upload a file', '← Back']
    menu = TerminalMenu(options, title='\nFiles')
    choice = menu.show()

    if choice is None or choice == 2:
        return
    elif choice == 0:
        try:
            data = client.list_files()
            format_file_list(data)
        except GatewayError as e:
            print_error(str(e))
    elif choice == 1:
        console.print('\n  Enter file path:')
        file_path = input('  > ').strip()
        if not file_path:
            return
        if not os.path.exists(file_path):
            print_error(f'File not found: {file_path}')
            return
        try:
            with console.status('Uploading...'):
                data = client.upload_file(file_path)
            print_success(f'Uploaded: {data.get("filename", "?")}')
            console.print(f'  Path: {data.get("input_path", "")}')
        except GatewayError as e:
            print_error(str(e))


def _health_flow(client):
    try:
        with console.status('Checking health...'):
            data = client.health()
        format_health_summary(data)
    except GatewayError as e:
        print_error(str(e))


def _select_file(client):
    try:
        data = client.list_files()
        files = data.get('files', [])
    except GatewayError:
        files = []

    options = []
    paths = []
    for f in files:
        filename = f.get('filename', '')
        path = f.get('path', f.get('input_path', ''))
        if not path and filename:
            path = f'/shared/uploads/{filename}'
        name = filename or path.split('/')[-1]
        size = f.get('size_mb', 0)
        options.append(f'{name}  ({size:.1f} MB)')
        paths.append(path)

    options.append('Enter path manually...')
    options.append('Upload a local file...')
    options.append('← Back')

    menu = TerminalMenu(options, title='\nSelect a file')
    choice = menu.show()

    if choice is None or choice == len(options) - 1:
        return None
    elif choice == len(options) - 3:
        console.print('\n  Enter /shared/ path:')
        path = input('  > ').strip()
        return path if path else None
    elif choice == len(options) - 2:
        console.print('\n  Enter local file path:')
        local_path = input('  > ').strip()
        if not local_path or not os.path.exists(local_path):
            print_error('File not found.')
            return None
        try:
            with console.status('Uploading...'):
                result = client.upload_file(local_path)
            print_success(f'Uploaded: {result.get("filename", "?")}')
            return result.get('input_path')
        except GatewayError as e:
            print_error(str(e))
            return None
    else:
        return paths[choice]


def _select_single_detector(client):
    try:
        data = client.list_detectors()
    except GatewayError as e:
        print_error(str(e))
        return None

    detectors = data.get('detectors', [])
    healthy = [d for d in detectors if d.get('container_status') == 'healthy']

    if not healthy:
        print_error('No healthy detectors available. Start some first.')
        return None

    options = [f'{d["name"]}  ({d.get("display_name", "")})' for d in healthy]
    options.append('← Back')

    menu = TerminalMenu(options, title='\nSelect a detector')
    choice = menu.show()

    if choice is None or choice == len(options) - 1:
        return None

    return healthy[choice]['name']


def _select_detectors(client, min_count=1):
    try:
        data = client.list_detectors()
    except GatewayError as e:
        print_error(str(e))
        return None

    detectors = data.get('detectors', [])
    healthy = [d for d in detectors if d.get('container_status') == 'healthy']

    if len(healthy) < min_count:
        print_error(f'Need at least {min_count} healthy detector(s). Only {len(healthy)} available.')
        return None

    options = [f'{d["name"]}  ({d.get("display_name", "")})' for d in healthy]

    menu = TerminalMenu(
        options,
        title=f'\nSelect detector(s) (Space to toggle, Enter to confirm, min {min_count})',
        multi_select=True,
        show_multi_select_hint=True,
    )
    selections = menu.show()

    if selections is None:
        return None

    if isinstance(selections, int):
        selections = (selections,)

    selected = [healthy[i]['name'] for i in selections]

    if len(selected) < min_count:
        print_error(f'At least {min_count} detector(s) required.')
        return None

    return selected


def _configure_detectors(client, detector_names):
    options = ['Skip (use defaults)', 'Set parameters...']
    menu = TerminalMenu(options, title='\nConfigure parameters?')
    choice = menu.show()

    if choice is None or choice == 0:
        return {}

    from cli.main import _parse_value

    schemas = {}
    for name in detector_names:
        try:
            data = client.get_detector(name)
            schema = data.get('manifest', {}).get('config_schema', {})
            if schema:
                schemas[name] = schema
        except GatewayError:
            pass

    if not schemas:
        print_info('No configurable parameters for selected detector(s).')
        return {}

    for name, schema in schemas.items():
        console.print(f'\n  [bold]{name}[/bold] parameters:')
        for param, spec in schema.items():
            default = spec.get('default', '')
            ptype = spec.get('type', '')
            desc = spec.get('description', '')
            pmin = spec.get('min')
            pmax = spec.get('max')
            range_str = f' [{pmin}-{pmax}]' if pmin is not None and pmax is not None else ''
            console.print(f'    {param} ({ptype}, default={default}{range_str}) — {desc}')

    console.print('\n  Enter config as key=value (one per line, empty line to finish).')
    if len(detector_names) > 1:
        console.print('  Use detector:key=value for per-detector overrides.')

    config = {}
    while True:
        line = input('  > ').strip()
        if not line:
            break
        if '=' not in line:
            print_error('Format: key=value or detector:key=value')
            continue

        left, raw_value = line.split('=', 1)
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

    if config:
        print_info(f'Config: {config}')

    return config


def _guess_input_type(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'):
        return 'image'
    if ext in ('.csv', '.json', '.txt'):
        return 'sensor_csv'
    return 'video'
