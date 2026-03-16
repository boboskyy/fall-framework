import os
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    print('Fall Detection Framework - Stop')
    print('=' * 40)
    print('Stopping all services (gateway, frontend, detectors)...')
    print()

    subprocess.run(
        'docker compose down',
        shell=True,
        check=True,
        cwd=PROJECT_DIR,
    )

    print()
    print('All services stopped.')


if __name__ == '__main__':
    main()
