import os
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
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


if __name__ == '__main__':
    main()
