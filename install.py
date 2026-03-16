import shutil
import subprocess
import sys


def run(cmd, check=True):
    print(f'  > {cmd}')
    return subprocess.run(cmd, shell=True, check=check, cwd=PROJECT_DIR)


def main():
    global PROJECT_DIR
    import os
    PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

    print('Fall Detection Framework - Install')
    print('=' * 40)

    # Check docker
    if not shutil.which('docker'):
        print('ERROR: docker not found. Install Docker first.')
        sys.exit(1)

    r = subprocess.run('docker info', shell=True, capture_output=True)
    if r.returncode != 0:
        print('ERROR: Docker daemon is not running.')
        sys.exit(1)

    print('[OK] Docker found and running')

    # Check docker compose
    r = subprocess.run('docker compose version', shell=True, capture_output=True)
    if r.returncode != 0:
        print('ERROR: docker compose not available.')
        sys.exit(1)

    print('[OK] Docker Compose found')

    # Build gateway + frontend
    print()
    print('Building gateway...')
    run('docker compose build gateway')

    print()
    print('Building frontend...')
    run('docker compose build frontend')

    print()
    print('Install complete.')
    print('Run: python start.py')


if __name__ == '__main__':
    main()
