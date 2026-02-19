
import uuid
import threading
from datetime import datetime
from typing import Dict, List, Optional

import docker

from gateway.models import BuildJob, BuildStatus, ContainerStatus


class BuildManager:

    COMPOSE_PROJECT = 'fall-framework'

    def __init__(self, registry):
        self.registry = registry
        self._builds: Dict[str, BuildJob] = {}
        self._lock = threading.Lock()
        try:
            self._docker = docker.from_env()
        except docker.errors.DockerException:
            self._docker = None

    def submit_build(self, detector_name: str, device: str = 'cpu') -> Dict:
        if device not in ('cpu', 'gpu'):
            return {
                'error': 'INVALID_PARAMETER',
                'message': f'device must be "cpu" or "gpu", got "{device}"'
            }

        detector = self.registry.get_detector(detector_name)
        if not detector:
            return {
                'error': 'NOT_FOUND',
                'message': f'Detector "{detector_name}" not found'
            }

        if detector.container_status == ContainerStatus.NOT_DOWNLOADED.value:
            return {
                'error': 'NOT_DOWNLOADED',
                'message': f'Detector "{detector_name}" repo not downloaded yet. '
                           f'Download first via POST /api/v1/detectors/{detector_name}/download'
            }

        if device == 'gpu' and not detector.gpu_capable:
            return {
                'error': 'GPU_NOT_SUPPORTED',
                'message': f'Detector "{detector_name}" does not support GPU'
            }

        if not self._docker:
            return {
                'error': 'DOCKER_UNAVAILABLE',
                'message': 'Docker socket not available'
            }

        service_name = detector.docker_service_name

        with self._lock:
            for build in self._builds.values():
                if (build.detector_name == detector_name
                        and build.status in (BuildStatus.QUEUED.value,
                                             BuildStatus.BUILDING.value)):
                    return {
                        'error': 'ALREADY_BUILDING',
                        'message': f'Detector "{detector_name}" is already being built',
                        'build_id': build.build_id
                    }

            build_id = f'bld-{uuid.uuid4()}'
            build_job = BuildJob(
                build_id=build_id,
                detector_name=detector_name,
                service_name=service_name,
                status=BuildStatus.BUILDING.value
            )
            self._builds[build_id] = build_job

        detector.container_status = ContainerStatus.BUILDING.value

        thread = threading.Thread(
            target=self._execute_build,
            args=(build_id, device),
            daemon=True
        )
        thread.start()

        return {
            'build_id': build_id,
            'detector': detector_name,
            'device': device,
            'status': build_job.status
        }

    def _execute_build(self, build_id: str, device: str = 'cpu'):
        build_job = self._builds[build_id]
        image_tag = f'{self.COMPOSE_PROJECT}-{build_job.service_name}'
        dockerfile_path = f'detectors/{build_job.detector_name}/Dockerfile'

        try:
            build_job.log_output += f'Building image {image_tag} (device={device})...\n'
            build_job.log_output += f'Dockerfile: {dockerfile_path}\n'
            build_job.log_output += f'Context: /project\n\n'

            resp = self._docker.api.build(
                path='/project',
                dockerfile=dockerfile_path,
                tag=image_tag,
                buildargs={'DEVICE': device},
                labels={'fallfw.device': device},
                rm=True,
                decode=True
            )

            for chunk in resp:
                if 'stream' in chunk:
                    build_job.log_output += chunk['stream']
                elif 'error' in chunk:
                    error_msg = chunk['error'].strip()
                    build_job.log_output += f'ERROR: {error_msg}\n'
                    build_job.status = BuildStatus.FAILED.value
                    build_job.error = error_msg
                    build_job.completed_at = datetime.utcnow().isoformat()
                    return

            build_job.status = BuildStatus.BUILT.value
            build_job.log_output += f'\nImage {image_tag} built successfully.\n'

            detector = self.registry.get_detector(build_job.detector_name)
            if detector:
                detector.container_status = ContainerStatus.STOPPED.value
                detector.device = device

        except docker.errors.BuildError as e:
            build_job.status = BuildStatus.FAILED.value
            build_job.error = str(e)
            build_job.log_output += f'\nBuild failed: {e}\n'

        except docker.errors.APIError as e:
            build_job.status = BuildStatus.FAILED.value
            build_job.error = str(e)
            build_job.log_output += f'\nDocker API error: {e}\n'

        except Exception as e:
            build_job.status = BuildStatus.FAILED.value
            build_job.error = str(e)
            build_job.log_output += f'\nUnexpected error: {e}\n'

        finally:
            if not build_job.completed_at:
                build_job.completed_at = datetime.utcnow().isoformat()
            if build_job.status == BuildStatus.FAILED.value:
                detector = self.registry.get_detector(build_job.detector_name)
                if detector and detector.container_status == ContainerStatus.BUILDING.value:
                    detector.container_status = ContainerStatus.NOT_BUILT.value

    def get_build(self, build_id: str) -> Optional[BuildJob]:
        return self._builds.get(build_id)

    def list_builds(self) -> List[Dict]:
        return [b.get_summary() for b in self._builds.values()]
