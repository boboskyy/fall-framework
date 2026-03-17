import os
import subprocess
import sys
import time
import urllib.request

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_URL = 'http://localhost:2999'


def wait_and_open(url, timeout=60):
    print(f'Waiting for frontend to be ready...')
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            import webbrowser
            webbrowser.open(url)
            print(f'Opened {url}')
            return
        except Exception:
            time.sleep(2)
    print(f'Frontend did not become ready in {timeout}s - open {url} manually.')


def main():
    open_browser = '--open' in sys.argv

    print('Fall Detection Framework - Start')
    print('=' * 40)
    print('Starting gateway and frontend...')
    print()

    subprocess.run(
        'docker compose up -d gateway frontend',
        shell=True,
        check=True,
        cwd=PROJECT_DIR,
    )

    print()
    print('Services starting:')
    print('  Gateway:  http://localhost:3000')
    print('  Frontend: http://localhost:2999')
    print()
    print('Detectors are started on-demand via the gateway API.')
    print('Run: python stop.py  to stop everything.')

    if open_browser:
        print()
        wait_and_open(FRONTEND_URL)


if __name__ == '__main__':
    main()
