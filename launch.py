
import os
import signal
import subprocess
import sys
import time
import urllib.request

RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
BOLD = '\033[1m'
RESET = '\033[0m'

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICES = ['gateway', 'frontend']

HEALTH_ENDPOINTS = {
    'gateway':  'http://localhost:3000/api/v1/health',
    'frontend': 'http://localhost:2999',
}

HEALTH_TIMEOUT = 60


def print_banner():
    print(f'''
{BOLD}{CYAN}╔══════════════════════════════════════╗
║   Fall Detection Framework Launcher  ║
║                                      ║
║   Open:  http://localhost:2999       ║
╚══════════════════════════════════════╝{RESET}
''')


def run(cmd, capture=False, check=True):
    kwargs = dict(cwd=PROJECT_DIR, check=check)
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return subprocess.run(cmd, **kwargs)


def check_docker():
    for cmd, label in [
        (['docker', '--version'], 'Docker'),
        (['docker', 'compose', 'version'], 'Docker Compose'),
    ]:
        try:
            result = run(cmd, capture=True)
            version = result.stdout.strip()
            print(f'  {GREEN}✓{RESET} {label}: {version}')
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f'''
{RED}{BOLD}ERROR: {label} is not installed or not running.{RESET}

Install Docker Desktop: https://docs.docker.com/get-docker/
Then make sure the Docker daemon is running.
''')
            sys.exit(1)
    print()


def images_exist():
    missing = []
    for service in SERVICES:
        result = run(
            ['docker', 'compose', 'images', '-q', service],
            capture=True, check=False,
        )
        if not result.stdout.strip():
            missing.append(service)
    return missing


def build_services(services):
    print(f'{CYAN}Building: {", ".join(services)}...{RESET}\n')
    run(['docker', 'compose', 'build'] + services)
    print(f'\n{GREEN}Build complete.{RESET}\n')


def start_services():
    print(f'{CYAN}Starting services...{RESET}')
    run(['docker', 'compose', 'up', '-d'] + SERVICES)
    print()


def poll_health():
    print(f'{CYAN}Waiting for services to become healthy (max {HEALTH_TIMEOUT}s)...{RESET}')
    healthy = {name: False for name in HEALTH_ENDPOINTS}
    start = time.time()
    dots = 0

    while time.time() - start < HEALTH_TIMEOUT:
        all_up = True
        for name, url in HEALTH_ENDPOINTS.items():
            if healthy[name]:
                continue
            try:
                req = urllib.request.Request(url, method='GET')
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status < 400:
                        healthy[name] = True
                        continue
            except Exception:
                pass
            all_up = False

        if all_up:
            break

        dots += 1
        print(f'\r  {"." * dots}', end='', flush=True)
        time.sleep(2)

    print('\r' + ' ' * (dots + 4))

    print(f'{BOLD}  Service      Port   Status{RESET}')
    print(f'  {"─" * 34}')
    rows = [
        ('Gateway',  '3000', healthy.get('gateway', False)),
        ('Frontend', '2999', healthy.get('frontend', False)),
    ]
    for label, port, up in rows:
        status = f'{GREEN}● healthy{RESET}' if up else f'{RED}● down{RESET}'
        print(f'  {label:<12}  {port:<6} {status}')
    print()

    if not all(healthy.values()):
        down = [n for n, v in healthy.items() if not v]
        print(f'{YELLOW}Warning: these services did not become healthy within {HEALTH_TIMEOUT}s: {", ".join(down)}')
        print(f'Check logs with: docker compose logs {" ".join(down)}{RESET}\n')


def stop_services():
    print(f'\n{CYAN}Stopping services...{RESET}')
    run(['docker', 'compose', 'stop'] + SERVICES, check=False)
    print(f'{GREEN}Services stopped. Goodbye.{RESET}')


def interactive_loop():
    print(f'{BOLD}Type "exit" or press Ctrl+C to stop all services and quit.{RESET}\n')
    try:
        while True:
            try:
                line = input(f'{CYAN}launch>{RESET} ').strip().lower()
            except EOFError:
                break
            if line in ('exit', 'quit', 'q'):
                break
    except KeyboardInterrupt:
        pass
    stop_services()


def main():
    signal.signal(signal.SIGINT, lambda *_: None)

    print_banner()

    print(f'{BOLD}Checking prerequisites...{RESET}')
    check_docker()

    missing = images_exist()
    if missing:
        print(f'{YELLOW}Missing Docker images for: {", ".join(missing)}{RESET}')
        answer = input(f'Build now? [Y/n] ').strip().lower()
        if answer in ('n', 'no'):
            print('Exiting without building.')
            sys.exit(0)
        build_services(missing)

    start_services()

    poll_health()

    interactive_loop()


if __name__ == '__main__':
    main()
