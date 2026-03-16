import os
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def run(cmd, check=False):
    print(f'  > {cmd}')
    return subprocess.run(cmd, shell=True, check=check, cwd=PROJECT_DIR)


def main():
    print('Fall Detection Framework - Uninstall')
    print('=' * 40)
    print()
    print('This will:')
    print('  - Stop and remove all containers')
    print('  - Remove all built images')
    print('  - Remove the docker network and volumes')
    print()

    answer = input('Continue? [y/N] ').strip().lower()
    if answer != 'y':
        print('Aborted.')
        sys.exit(0)

    print()

    # Stop everything
    print('Stopping containers...')
    run('docker compose down --remove-orphans')

    # Get project name for image prefix
    project = os.path.basename(PROJECT_DIR).lower().replace('-', '').replace('_', '')

    # Remove images built by compose
    print()
    print('Removing images...')
    r = subprocess.run(
        'docker compose config --images',
        shell=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_DIR,
    )
    if r.returncode == 0:
        images = [img.strip() for img in r.stdout.strip().splitlines() if img.strip()]
        for img in images:
            run(f'docker rmi {img}')

    # Remove volumes
    print()
    print('Removing volumes...')
    run(f'docker volume rm {project}_shared')

    # Remove network
    print()
    print('Removing network...')
    run(f'docker network rm {project}_fall-detection')

    # Clean up downloaded detector repos
    print()
    print('Cleaning downloaded detector repos...')
    detectors_dir = os.path.join(PROJECT_DIR, 'detectors')
    if os.path.isdir(detectors_dir):
        import shutil
        for name in os.listdir(detectors_dir):
            det_path = os.path.join(detectors_dir, name)
            if not os.path.isdir(det_path) or name.startswith('_'):
                continue
            repo_dir = os.path.join(det_path, 'repo')
            if os.path.isdir(repo_dir):
                print(f'  Removing {name}/repo/')
                shutil.rmtree(repo_dir)
            models_dir = os.path.join(det_path, 'models')
            if os.path.isdir(models_dir):
                print(f'  Removing {name}/models/')
                shutil.rmtree(models_dir)
            marker = os.path.join(det_path, '.download_complete')
            if os.path.isfile(marker):
                os.remove(marker)

    # Clean up downloaded datasets
    print()
    print('Cleaning downloaded datasets...')
    datasets_dir = os.path.join(PROJECT_DIR, 'datasets')
    if os.path.isdir(datasets_dir):
        import shutil
        for name in os.listdir(datasets_dir):
            ds_path = os.path.join(datasets_dir, name)
            if os.path.isdir(ds_path):
                print(f'  Removing datasets/{name}/')
                shutil.rmtree(ds_path)

    # Clean shared volume contents
    print()
    print('Cleaning shared directory...')
    shared_dir = os.path.join(PROJECT_DIR, 'shared')
    if os.path.isdir(shared_dir):
        import shutil
        for name in os.listdir(shared_dir):
            path = os.path.join(shared_dir, name)
            if name == '.gitkeep':
                continue
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

    print()
    print('Uninstall complete.')


if __name__ == '__main__':
    main()
