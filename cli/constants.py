
import os

DEFAULT_GATEWAY_URL = 'http://localhost:3000'
GATEWAY_ENV_VAR = 'FALLFW_GATEWAY_URL'
GATEWAY_URL = os.environ.get(GATEWAY_ENV_VAR, DEFAULT_GATEWAY_URL)

REQUEST_TIMEOUT = 30
UPLOAD_TIMEOUT = 120
DETECT_SYNC_TIMEOUT = 600
POLL_INTERVAL = 2.0

STATUS_SYMBOLS = {
    'healthy': '[green]●[/green]',
    'stopped': '[dim]○[/dim]',
    'unhealthy': '[red]●[/red]',
    'error': '[red]✗[/red]',
    'not_built': '[dim]—[/dim]',
    'unknown': '[yellow]?[/yellow]',
    'starting': '[yellow]◐[/yellow]',
    'completed': '[green]✓[/green]',
    'running': '[cyan]↻[/cyan]',
    'pending': '[dim]…[/dim]',
    'failed': '[red]✗[/red]',
    'partial': '[yellow]◑[/yellow]',
}
