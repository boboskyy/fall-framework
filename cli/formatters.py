
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from cli.constants import STATUS_SYMBOLS

console = Console()


def _status_icon(status):
    return STATUS_SYMBOLS.get(status, f'[dim]{status}[/dim]')


def print_error(message):
    console.print(f'[red]Error:[/red] {message}')


def print_success(message):
    console.print(f'[green]OK:[/green] {message}')


def print_warning(message):
    console.print(f'[yellow]Warning:[/yellow] {message}')


def print_info(message):
    console.print(f'[cyan]Info:[/cyan] {message}')


def format_detector_list(data):
    detectors = data.get('detectors', [])

    if not detectors:
        print_warning('No detectors registered.')
        return

    table = Table(
        title='Registered Detectors',
        box=box.ROUNDED,
        show_lines=False
    )
    table.add_column('Status', width=3, justify='center')
    table.add_column('Name', style='bold')
    table.add_column('Display Name')
    table.add_column('Category')
    table.add_column('Port', justify='right')
    table.add_column('Input Types')

    for d in detectors:
        status = d.get('container_status', 'unknown')
        table.add_row(
            _status_icon(status),
            d.get('name', ''),
            d.get('display_name', ''),
            d.get('category', ''),
            str(d.get('port', '')),
            ', '.join(d.get('supported_input_types', []))
        )

    console.print(table)
    console.print(f'\n  [dim]{data.get("count", 0)} detector(s) registered[/dim]')


def format_detector_detail(data):
    det = data.get('detector', {})
    manifest = data.get('manifest', {})

    status = det.get('container_status', 'unknown')
    title = f'{det.get("display_name", det.get("name", "?"))} {_status_icon(status)}'

    lines = []
    lines.append(f'[bold]Name:[/bold]       {det.get("name", "")}')
    lines.append(f'[bold]Version:[/bold]    {det.get("version", "")}')
    lines.append(f'[bold]Category:[/bold]   {det.get("category", "")}')
    lines.append(f'[bold]Port:[/bold]       {det.get("port", "")}')
    lines.append(f'[bold]Status:[/bold]     {status}')
    lines.append(f'[bold]Multi-person:[/bold] {"yes" if det.get("multi_person") else "no"}')
    lines.append(f'[bold]GPU:[/bold]        {"required" if det.get("requires_gpu") else "not required"}')
    lines.append(f'[bold]Input types:[/bold] {", ".join(det.get("supported_input_types", []))}')

    desc = det.get('description', '')
    if desc:
        lines.append(f'\n[dim]{desc}[/dim]')

    repo = det.get('github_url', '') or manifest.get('repository', manifest.get('repo_url', ''))
    if repo:
        lines.append(f'\n[bold]Repository:[/bold] {repo}')

    model_info = manifest.get('model_info', {})
    if model_info:
        lines.append(f'\n[bold]Model:[/bold]')
        lines.append(f'  Architecture: {model_info.get("architecture", "?")}')
        lines.append(f'  Framework:    {model_info.get("framework", "?")}')
        if model_info.get('weights_file'):
            lines.append(f'  Weights:      {model_info["weights_file"]}')

    config_schema = manifest.get('config_schema', {})
    if config_schema:
        lines.append(f'\n[bold]Config options:[/bold]')
        for param, spec in config_schema.items():
            default = spec.get('default', '')
            desc_text = spec.get('description', '')
            lines.append(f'  {param} = {default}  [dim]({desc_text})[/dim]')

    console.print(Panel('\n'.join(lines), title=title, box=box.ROUNDED))


def format_health_summary(data):
    det_info = data.get('detectors', {})
    details = data.get('status_details', [])

    console.print(f'\n  Gateway: [green]healthy[/green]')
    console.print(
        f'  Detectors: [green]{det_info.get("healthy", 0)}[/green] healthy, '
        f'[dim]{det_info.get("stopped", 0)}[/dim] stopped, '
        f'[red]{det_info.get("unhealthy", 0)}[/red] unhealthy'
    )

    if details:
        console.print()
        for d in details:
            icon = _status_icon(d.get('status', 'unknown'))
            console.print(f'  {icon} {d["name"]}  [dim]{d.get("status", "")}[/dim]')

    console.print()


def format_file_list(data):
    files = data.get('files', [])

    if not files:
        print_info('No files uploaded yet.')
        return

    table = Table(box=box.SIMPLE, show_lines=False)
    table.add_column('Filename', style='bold')
    table.add_column('Size', justify='right')
    table.add_column('Path')

    for f in files:
        size_mb = f.get('size_mb', 0)
        size_str = f'{size_mb:.1f} MB' if size_mb is not None else '?'
        filename = f.get('filename', '')
        path = f.get('path', f.get('input_path', ''))
        if not path and filename:
            path = f'/shared/uploads/{filename}'
        table.add_row(filename, size_str, path)

    console.print(table)
    console.print(f'  [dim]{data.get("count", len(files))} file(s)[/dim]')


def format_detection_result(data, raw_json=False):
    import json

    if raw_json:
        console.print_json(json.dumps(data, indent=2, default=str))
        return

    status = data.get('status', 'unknown')
    job_id = data.get('job_id', '?')
    label = data.get('label')
    label_str = f'  [dim]"{label}"[/dim]' if label else ''

    console.print(f'\n  Job: [bold]{job_id}[/bold]{label_str}  Status: {_status_icon(status)} {status}')

    result = data.get('result')
    results = data.get('results', {})
    sub_tasks = data.get('sub_tasks', {})

    if result:
        _print_single_result(result)
    elif results:
        for det_name, det_result in results.items():
            console.print(f'\n  [bold cyan]--- {det_name} ---[/bold cyan]')
            if det_result is None:
                print_error(f'  {det_name}: no result (failed)')
            else:
                _print_single_result(det_result)
    elif sub_tasks:
        for det_name, task in sub_tasks.items():
            console.print(f'\n  [bold cyan]--- {det_name} ---[/bold cyan]')
            task_result = task.get('result') if isinstance(task, dict) else None
            if task_result:
                _print_single_result(task_result)
            else:
                task_status = task.get('status', '?') if isinstance(task, dict) else '?'
                task_error = task.get('error') if isinstance(task, dict) else None
                console.print(f'  Status: {task_status}')
                if task_error:
                    print_error(f'  {task_error}')

    console.print()


def _print_single_result(result):
    summary = result.get('summary', {})
    total = result.get('total_frames', 0)
    processed = result.get('processed_frames', 0)

    if summary:
        fall_frames = summary.get('fall_frames_count', summary.get('fall_frame_count', 0))
        fall_pct = summary.get('fall_percentage', 0)
        total_analyzed = summary.get('total_frames_analyzed', processed)
        fall_detected = fall_frames > 0 or fall_pct > 0

        status_text = '[red bold]FALL DETECTED[/red bold]' if fall_detected else '[green]No fall[/green]'

        console.print(f'  Result: {status_text}')
        console.print(f'  Frames: {total_analyzed}/{total} analyzed')
        if fall_frames > 0:
            console.print(f'  Fall frames: {fall_frames} ({fall_pct:.1f}%)')
    elif total:
        console.print(f'  Frames: {processed}/{total}')

    config_used = result.get('config_used')
    if config_used:
        console.print(f'  [bold]Config used:[/bold]')
        for key, value in config_used.items():
            console.print(f'    {key}: {value}')

    events = result.get('fall_events', [])
    if events:
        console.print(f'  Fall events: {len(events)} frame(s)')
        frames = [evt.get('frame_index', evt.get('start_frame')) for evt in events]
        frames = [f for f in frames if f is not None]
        if frames:
            ranges = _condense_frame_ranges(frames)
            for start, end in ranges:
                if start == end:
                    console.print(f'    frame {start}')
                else:
                    console.print(f'    frames {start}-{end} ({end - start + 1} frames)')


def _condense_frame_ranges(frames):
    if not frames:
        return []
    frames = sorted(set(frames))
    ranges = []
    start = frames[0]
    end = frames[0]
    for f in frames[1:]:
        if f <= end + 2:
            end = f
        else:
            ranges.append((start, end))
            start = f
            end = f
    ranges.append((start, end))
    return ranges


def format_comparison_result(data, raw_json=False):
    import json

    if raw_json:
        console.print_json(json.dumps(data, indent=2, default=str))
        return

    status = data.get('status', 'unknown')
    comp_id = data.get('comparison_id', '?')
    label = data.get('label')
    label_str = f'  [dim]"{label}"[/dim]' if label else ''

    console.print(f'\n  Comparison: [bold]{comp_id}[/bold]{label_str}  Status: {_status_icon(status)} {status}')

    if status != 'completed':
        if data.get('error'):
            print_error(data['error'])
        return

    summaries = data.get('detector_summaries', [])
    if summaries:
        table = Table(title='Detector Summaries', box=box.SIMPLE)
        table.add_column('Detector', style='bold')
        table.add_column('Fall?', justify='center')
        table.add_column('Frames', justify='right')
        table.add_column('Fall Frames', justify='right')
        table.add_column('Fall %', justify='right')
        table.add_column('Events', justify='right')

        for s in summaries:
            fall_frames = s.get('fall_frames', 0)
            fall_pct = s.get('fall_percentage', 0)
            total = s.get('total_frames', 0)
            ranges = s.get('fall_time_ranges_ms', [])
            has_fall = fall_frames > 0

            fall = '[red]YES[/red]' if has_fall else '[green]no[/green]'
            table.add_row(
                s.get('detector', ''),
                fall,
                str(total),
                str(fall_frames),
                f'{fall_pct:.1f}',
                str(len(ranges))
            )

        console.print(table)

    results = data.get('results', {})
    if results:
        for det_name, det_result in results.items():
            if isinstance(det_result, dict) and det_result.get('config_used'):
                config_used = det_result['config_used']
                console.print(f'  [bold]{det_name}[/bold] config:')
                for key, value in config_used.items():
                    console.print(f'    {key}: {value}')

    matrix = data.get('agreement_matrix', {})
    matrix_data = matrix.get('matrix', {})
    if matrix_data:
        console.print('\n  [bold]Agreement Matrix (Jaccard):[/bold]')
        det_names = list(matrix_data.keys())
        mtable = Table(box=box.SIMPLE, show_header=True)
        mtable.add_column('', style='bold')
        for name in det_names:
            mtable.add_column(name[:20], justify='right')

        for row_name in det_names:
            row_vals = []
            for col_name in det_names:
                val = matrix_data.get(row_name, {}).get(col_name, 0)
                if row_name == col_name:
                    row_vals.append('[dim]1.00[/dim]')
                elif val >= 0.7:
                    row_vals.append(f'[green]{val:.2f}[/green]')
                elif val >= 0.3:
                    row_vals.append(f'[yellow]{val:.2f}[/yellow]')
                else:
                    row_vals.append(f'[red]{val:.2f}[/red]')
            mtable.add_row(row_name[:20], *row_vals)

        console.print(mtable)

    notes = data.get('comparison_notes', [])
    if notes:
        console.print('\n  [bold]Notes:[/bold]')
        for note in notes:
            console.print(f'    - {note}')

    console.print()


def format_batch_status(data, raw_json=False):
    import json

    if raw_json:
        console.print_json(json.dumps(data, indent=2, default=str))
        return

    batch_id = data.get('batch_id', '?')
    status = data.get('status', 'unknown')
    label = data.get('label')
    label_str = f'  [dim]"{label}"[/dim]' if label else ''

    console.print(f'\n  Batch: [bold]{batch_id}[/bold]{label_str}  Status: {_status_icon(status)} {status}')

    progress = data.get('progress', {})
    if progress:
        total = progress.get('total_tasks', 0)
        completed = progress.get('completed_tasks', 0)
        failed = progress.get('failed_tasks', 0)
        pct = progress.get('progress_pct', 0)
        console.print(f'  Progress: {completed}/{total} tasks ({pct:.1f}%)')
        if failed:
            console.print(f'  [red]Failed: {failed}[/red]')

    results = data.get('results', {})
    if results:
        console.print(f'\n  [bold]Results by file:[/bold]')
        for filename, det_results in results.items():
            console.print(f'\n  [cyan]{filename}[/cyan]')
            if isinstance(det_results, dict):
                for det_name, det_result in det_results.items():
                    if det_result and isinstance(det_result, dict):
                        summary = det_result.get('summary', {})
                        fall_frames = summary.get('fall_frames_count',
                                                  summary.get('fall_frame_count', 0))
                        fall_pct = summary.get('fall_percentage', 0)
                        has_fall = (fall_frames or 0) > 0 or (fall_pct or 0) > 0
                        verdict = '[red]FALL[/red]' if has_fall else '[green]OK[/green]'
                        console.print(f'    {det_name}: {verdict}')
                    else:
                        console.print(f'    {det_name}: [dim]no result[/dim]')

    console.print()


def format_job_list(data):
    jobs = data.get('jobs', [])

    if not jobs:
        print_info('No jobs found.')
        return

    table = Table(box=box.SIMPLE, show_lines=False)
    table.add_column('Status', width=3, justify='center')
    table.add_column('Job ID', style='bold')
    table.add_column('Label')
    table.add_column('Detectors')
    table.add_column('Input')
    table.add_column('Created')

    for j in jobs:
        status = j.get('status', 'unknown')
        label = j.get('label') or ''
        detectors = ', '.join(j.get('detector_names', []))
        input_path = j.get('input_path', '')
        filename = input_path.split('/')[-1] if input_path else ''
        created = j.get('created_at', '')[:19]

        table.add_row(
            _status_icon(status),
            j.get('job_id', '?')[:12],
            label[:30],
            detectors[:40],
            filename[:30],
            created
        )

    console.print(table)
    console.print(f'  [dim]{data.get("count", len(jobs))} job(s)[/dim]')


def format_status(data):
    status = data.get('status', 'unknown')
    icon = _status_icon(status)
    label = data.get('label')
    label_str = f'  [dim]"{label}"[/dim]' if label else ''

    if 'job_id' in data:
        id_label = f'Job: {data["job_id"]}'
    elif 'batch_id' in data:
        id_label = f'Batch: {data["batch_id"]}'
    elif 'comparison_id' in data:
        id_label = f'Comparison: {data["comparison_id"]}'
    else:
        id_label = 'Unknown'

    console.print(f'\n  {id_label}{label_str}  {icon} {status}')

    progress = data.get('progress', {})
    if progress:
        total = progress.get('total', progress.get('total_tasks', 0))
        completed = progress.get('completed', progress.get('completed_tasks', 0))
        pct = progress.get('progress_pct', 0)
        console.print(f'  Progress: {completed}/{total} ({pct:.1f}%)')

    sub_statuses = data.get('sub_task_statuses', {})
    if sub_statuses:
        for name, st in sub_statuses.items():
            console.print(f'    {_status_icon(st)} {name}: {st}')

    console.print()
