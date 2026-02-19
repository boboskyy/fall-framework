
import os
import json
import requests
import docker
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from gateway.models import DetectorInfo, ContainerStatus


class DetectorRegistry:

    COMPOSE_PROJECT = 'fall-framework'
    NETWORK_NAME = 'fall-framework_fall-detection'

    def __init__(self, detectors_dir='/detectors', health_timeout=2):
        self.detectors_dir = detectors_dir
        self.health_timeout = health_timeout
        self._detectors: Dict[str, DetectorInfo] = {}
        self._manifests: Dict[str, Dict] = {}
        self._host_shared_path: Optional[str] = None
        try:
            self._docker = docker.from_env()
        except docker.errors.DockerException:
            self._docker = None
            print('Warning: Docker socket not available - start/stop disabled')

    def scan_manifests(self):
        detectors_path = Path(self.detectors_dir)
        if not detectors_path.exists():
            raise RuntimeError(f'Detectors directory not found: {self.detectors_dir}')

        found_names = set()
        found_count = 0
        for manifest_path in detectors_path.glob('*/manifest.json'):
            detector_name = manifest_path.parent.name

            if detector_name == '_template':
                continue

            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)

                found_names.add(detector_name)

                self._manifests[detector_name] = manifest

                service_name = manifest.get('docker_service_name', detector_name)
                existing = self._detectors.get(detector_name)
                download_config = manifest.get('download')
                if existing:
                    initial_status = existing.container_status
                elif self._image_exists(service_name):
                    initial_status = 'unknown'
                elif download_config and not self._is_downloaded(detector_name, download_config):
                    initial_status = ContainerStatus.NOT_DOWNLOADED.value
                else:
                    initial_status = ContainerStatus.NOT_BUILT.value

                gpu_support = manifest.get('gpu_support', {})
                gpu_capable = gpu_support.get('capable', False)
                if existing:
                    device = existing.device
                else:
                    device = self._get_image_device(service_name)

                detector_info = DetectorInfo(
                    name=manifest.get('name', detector_name),
                    display_name=manifest.get('display_name', detector_name.replace('_', ' ').title()),
                    version=manifest.get('version', '1.0.0'),
                    description=manifest.get('description', ''),
                    category=manifest.get('category', 'unknown'),
                    port=manifest.get('port', 5000),
                    internal_port=manifest.get('internal_port', 5000),
                    docker_service_name=service_name,
                    github_url=manifest.get('github_url', manifest.get('repository', manifest.get('repo_url', ''))),
                    tags=manifest.get('tags', []),
                    supported_input_types=manifest.get('supported_input_types', ['video']),
                    multi_person=manifest.get('multi_person', False),
                    requires_gpu=manifest.get('requires_gpu', False),
                    gpu_capable=gpu_capable,
                    device=device,
                    container_status=initial_status,
                    last_health_check=existing.last_health_check if existing else None,
                    health_check_error=existing.health_check_error if existing else None
                )

                self._detectors[detector_name] = detector_info
                found_count += 1

            except Exception as e:
                print(f'Warning: Failed to load manifest for {detector_name}: {e}')

        stale = set(self._detectors.keys()) - found_names
        for name in stale:
            del self._detectors[name]
            self._manifests.pop(name, None)
            print(f'Registry: Removed stale detector "{name}" (manifest not found)')

        print(f'Registry: Scanned {found_count} detector(s)')
        return found_count

    def rescan_manifests(self) -> Dict:
        before = set(self._detectors.keys())
        count = self.scan_manifests()
        after = set(self._detectors.keys())

        added = sorted(after - before)
        removed = sorted(before - after)
        return {
            'total': count,
            'added': added,
            'added_count': len(added),
            'removed': removed,
            'removed_count': len(removed),
        }

    def get_all_detectors(self, refresh_health=False) -> List[DetectorInfo]:
        if refresh_health:
            self.refresh_all_health()
        return list(self._detectors.values())

    def get_detector(self, name: str) -> Optional[DetectorInfo]:
        return self._detectors.get(name)

    def get_manifest(self, name: str) -> Optional[Dict]:
        return self._manifests.get(name)

    def check_health(self, name: str) -> Dict:
        detector = self._detectors.get(name)
        if not detector:
            return {
                'status': 'not_found',
                'error': f'Detector {name} not registered'
            }

        health_url = f'http://{detector.docker_service_name}:{detector.internal_port}/health'

        try:
            response = requests.get(health_url, timeout=self.health_timeout)
            if response.status_code == 200:
                detector.container_status = ContainerStatus.HEALTHY.value
                detector.last_health_check = datetime.utcnow().isoformat()
                detector.health_check_error = None
                return {
                    'status': 'healthy',
                    'detector': name,
                    'response': response.json()
                }
            else:
                detector.container_status = ContainerStatus.UNHEALTHY.value
                detector.last_health_check = datetime.utcnow().isoformat()
                detector.health_check_error = f'HTTP {response.status_code}'
                return {
                    'status': 'unhealthy',
                    'detector': name,
                    'error': f'HTTP {response.status_code}'
                }

        except requests.exceptions.ConnectionError:
            if detector.container_status not in (
                ContainerStatus.NOT_DOWNLOADED.value,
                ContainerStatus.DOWNLOADING.value,
                ContainerStatus.NOT_BUILT.value,
                ContainerStatus.BUILDING.value,
            ):
                detector.container_status = ContainerStatus.STOPPED.value
            detector.last_health_check = datetime.utcnow().isoformat()
            detector.health_check_error = 'Connection refused'
            return {
                'status': detector.container_status,
                'detector': name,
                'error': 'Container not running or unreachable'
            }

        except requests.exceptions.Timeout:
            detector.container_status = ContainerStatus.UNHEALTHY.value
            detector.last_health_check = datetime.utcnow().isoformat()
            detector.health_check_error = 'Timeout'
            return {
                'status': 'unhealthy',
                'detector': name,
                'error': 'Health check timeout'
            }

        except Exception as e:
            detector.container_status = ContainerStatus.ERROR.value
            detector.last_health_check = datetime.utcnow().isoformat()
            detector.health_check_error = str(e)
            return {
                'status': 'error',
                'detector': name,
                'error': str(e)
            }

    def refresh_all_health(self):
        for name in self._detectors.keys():
            self.check_health(name)

    def get_compatible_detectors(self, input_type: str) -> List[DetectorInfo]:
        compatible = []
        for detector in self._detectors.values():
            if input_type in detector.supported_input_types:
                compatible.append(detector)
        return compatible

    def get_healthy_detectors(self) -> List[DetectorInfo]:
        return [d for d in self._detectors.values()
                if d.container_status == ContainerStatus.HEALTHY.value]

    def validate_detectors(self, detector_names: List[str], input_type: str = None) -> Dict:
        errors = []
        warnings = []
        valid_detectors = []

        for name in detector_names:
            detector = self.get_detector(name)

            if not detector:
                errors.append(f'Detector "{name}" not found')
                continue

            if input_type and input_type not in detector.supported_input_types:
                errors.append(
                    f'Detector "{name}" does not support input type "{input_type}". '
                    f'Supported: {", ".join(detector.supported_input_types)}'
                )
                continue

            if detector.container_status != ContainerStatus.HEALTHY.value:
                warnings.append(
                    f'Detector "{name}" is not healthy (status: {detector.container_status}). '
                    f'Start with: docker compose up {name}'
                )

            valid_detectors.append(name)

        return {
            'valid': len(errors) == 0,
            'valid_detectors': valid_detectors,
            'errors': errors,
            'warnings': warnings
        }

    def _is_downloaded(self, detector_name: str, download_config: dict) -> bool:
        marker = Path(self.detectors_dir) / detector_name / '.download_complete'
        if not marker.exists():
            return False
        try:
            with open(marker) as f:
                info = json.load(f)
            return info.get('sha256') == download_config.get('sha256')
        except (json.JSONDecodeError, OSError):
            return False

    def _find_container(self, service_name: str):
        if not self._docker:
            return None
        try:
            containers = self._docker.containers.list(
                all=True,
                filters={'label': f'com.docker.compose.service={service_name}'}
            )
            return containers[0] if containers else None
        except docker.errors.DockerException:
            return None

    def _image_exists(self, service_name: str) -> bool:
        if not self._docker:
            return False
        image_tag = f'{self.COMPOSE_PROJECT}-{service_name}'
        try:
            self._docker.images.get(image_tag)
            return True
        except docker.errors.ImageNotFound:
            return False
        except docker.errors.DockerException:
            return False

    def _get_image_device(self, service_name: str) -> str:
        if not self._docker:
            return 'cpu'
        image_tag = f'{self.COMPOSE_PROJECT}-{service_name}'
        try:
            image = self._docker.images.get(image_tag)
            labels = image.labels or {}
            return labels.get('fallfw.device', 'cpu')
        except docker.errors.DockerException:
            return 'cpu'

    def _get_host_shared_path(self) -> Optional[str]:
        if self._host_shared_path:
            return self._host_shared_path

        if not self._docker:
            return None

        try:
            hostname = os.environ.get('HOSTNAME', '')
            if not hostname:
                return None
            container = self._docker.containers.get(hostname)
            for mount in container.attrs.get('Mounts', []):
                if mount.get('Destination') == '/shared':
                    self._host_shared_path = mount.get('Source')
                    return self._host_shared_path
        except docker.errors.DockerException:
            pass

        return None

    def start_container(self, name: str) -> Dict:
        detector = self._detectors.get(name)
        if not detector:
            return {'error': 'NOT_FOUND', 'message': f'Detector "{name}" not found'}

        if detector.container_status == ContainerStatus.NOT_DOWNLOADED.value:
            return {
                'error': 'NOT_DOWNLOADED',
                'message': f'Detector "{name}" repo not downloaded yet. '
                           f'Download first via POST /api/v1/detectors/{name}/download'
            }

        if not self._docker:
            return {'error': 'DOCKER_UNAVAILABLE', 'message': 'Docker socket not available'}

        service_name = detector.docker_service_name
        container = self._find_container(service_name)

        if container:
            try:
                status = container.status
                if status == 'running':
                    return {
                        'status': 'already_running',
                        'detector': name,
                        'container': container.name,
                        'message': f'{name} is already running'
                    }

                container.start()
                detector.container_status = ContainerStatus.STARTING.value
                return {
                    'status': 'started',
                    'detector': name,
                    'container': container.name,
                    'message': f'{name} started successfully'
                }

            except docker.errors.APIError as e:
                error_msg = str(e)
                if 'device driver' in error_msg and 'gpu' in error_msg.lower():
                    try:
                        container.remove(force=True)
                    except docker.errors.DockerException:
                        pass
                    detector.container_status = ContainerStatus.STOPPED.value
                    return {
                        'error': 'GPU_UNAVAILABLE',
                        'message': (
                            f'No GPU driver available on this host. '
                            f'Rebuild as CPU: POST /api/v1/detectors/{name}/build '
                            f'with {{"device": "cpu"}}'
                        )
                    }
                return {'error': 'DOCKER_ERROR', 'message': error_msg}

        if not self._image_exists(service_name):
            return {
                'error': 'NOT_BUILT',
                'message': f'Image not built for "{service_name}". '
                           f'Build first via POST /api/v1/detectors/{name}/build'
            }

        return self._create_container(name, detector)

    def _create_container(self, name: str, detector: 'DetectorInfo') -> Dict:
        service_name = detector.docker_service_name
        image_tag = f'{self.COMPOSE_PROJECT}-{service_name}'
        container_name = f'{self.COMPOSE_PROJECT}-{service_name}-1'

        volumes = {}
        host_shared = self._get_host_shared_path()
        if host_shared:
            volumes[host_shared] = {'bind': '/shared', 'mode': 'ro'}

        environment = {'FLASK_ENV': 'production'}

        device_requests = None
        if detector.device == 'gpu':
            device_requests = [
                docker.types.DeviceRequest(
                    count=1,
                    capabilities=[['gpu']]
                )
            ]

        try:
            create_kwargs = dict(
                image=image_tag,
                name=container_name,
                detach=True,
                ports={'5000/tcp': detector.port},
                volumes=volumes,
                environment=environment,
                labels={
                    'com.docker.compose.service': service_name,
                    'com.docker.compose.project': self.COMPOSE_PROJECT
                },
                healthcheck={
                    'test': ['CMD', 'curl', '-f', 'http://localhost:5000/health'],
                    'interval': 30_000_000_000,
                    'timeout': 10_000_000_000,
                    'retries': 3,
                    'start_period': 20_000_000_000
                }
            )
            if device_requests:
                create_kwargs['device_requests'] = device_requests

            container = self._docker.containers.create(**create_kwargs)

            network = self._docker.networks.get(self.NETWORK_NAME)
            network.connect(container, aliases=[service_name])

            container.start()

            detector.container_status = ContainerStatus.STARTING.value
            return {
                'status': 'created',
                'detector': name,
                'container': container.name,
                'message': f'{name} container created and started'
            }

        except docker.errors.APIError as e:
            error_msg = str(e)
            if 'device driver' in error_msg and 'gpu' in error_msg.lower():
                try:
                    self._docker.containers.get(container_name).remove(force=True)
                except docker.errors.DockerException:
                    pass
                detector.container_status = ContainerStatus.STOPPED.value
                return {
                    'error': 'GPU_UNAVAILABLE',
                    'message': (
                        f'No GPU driver available on this host. '
                        f'Rebuild as CPU: POST /api/v1/detectors/{name}/build '
                        f'with {{"device": "cpu"}}'
                    )
                }
            return {'error': 'DOCKER_ERROR', 'message': f'Failed to create container: {e}'}

    def stop_container(self, name: str) -> Dict:
        detector = self._detectors.get(name)
        if not detector:
            return {'error': 'NOT_FOUND', 'message': f'Detector "{name}" not found'}

        if not self._docker:
            return {'error': 'DOCKER_UNAVAILABLE', 'message': 'Docker socket not available'}

        service_name = detector.docker_service_name
        container = self._find_container(service_name)

        if not container:
            return {
                'error': 'CONTAINER_NOT_FOUND',
                'message': f'No container for service "{service_name}".'
            }

        try:
            status = container.status
            if status != 'running':
                detector.container_status = ContainerStatus.STOPPED.value
                return {
                    'status': 'already_stopped',
                    'detector': name,
                    'container': container.name,
                    'message': f'{name} is not running (status: {status})'
                }

            container.stop(timeout=10)
            detector.container_status = ContainerStatus.STOPPED.value
            return {
                'status': 'stopped',
                'detector': name,
                'container': container.name,
                'message': f'{name} stopped successfully'
            }

        except docker.errors.APIError as e:
            return {'error': 'DOCKER_ERROR', 'message': str(e)}

    def uninstall_container(self, name: str) -> Dict:
        detector = self._detectors.get(name)
        if not detector:
            return {'error': 'NOT_FOUND', 'message': f'Detector "{name}" not found'}

        if not self._docker:
            return {'error': 'DOCKER_UNAVAILABLE', 'message': 'Docker socket not available'}

        service_name = detector.docker_service_name
        image_tag = f'{self.COMPOSE_PROJECT}-{service_name}'
        removed_container = False
        removed_image = False

        container = self._find_container(service_name)
        if container:
            try:
                if container.status == 'running':
                    container.stop(timeout=10)
                container.remove(force=True)
                removed_container = True
            except docker.errors.APIError as e:
                return {
                    'error': 'DOCKER_ERROR',
                    'message': f'Failed to remove container: {e}'
                }

        if self._image_exists(service_name):
            try:
                self._docker.images.remove(image_tag, force=True)
                removed_image = True
            except docker.errors.APIError as e:
                return {
                    'error': 'DOCKER_ERROR',
                    'message': f'Container removed but failed to remove image: {e}'
                }

        if not removed_container and not removed_image:
            return {
                'status': 'nothing_to_remove',
                'detector': name,
                'message': f'{name} has no container or image to remove'
            }

        download_config = self._manifests.get(name, {}).get('download')
        if download_config and not self._is_downloaded(name, download_config):
            detector.container_status = ContainerStatus.NOT_DOWNLOADED.value
        else:
            detector.container_status = ContainerStatus.NOT_BUILT.value
        return {
            'status': 'uninstalled',
            'detector': name,
            'removed_container': removed_container,
            'removed_image': removed_image,
            'message': f'{name} uninstalled successfully'
        }
