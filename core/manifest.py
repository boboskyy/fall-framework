from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json
import os


@dataclass
class DockerConfig:
    context: str = '../..'
    dockerfile: str = ''
    runtime: Optional[str] = None
    shm_size: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'DockerConfig':
        return cls(
            context=data.get('context', '../..'),
            dockerfile=data.get('dockerfile', ''),
            runtime=data.get('runtime'),
            shm_size=data.get('shm_size')
        )

    def to_dict(self) -> Dict:
        result = {
            'context': self.context,
            'dockerfile': self.dockerfile
        }
        if self.runtime:
            result['runtime'] = self.runtime
        if self.shm_size:
            result['shm_size'] = self.shm_size
        return result


@dataclass
class HealthCheckConfig:
    endpoint: str = '/health'
    interval_seconds: int = 10
    timeout_seconds: int = 5
    retries: int = 3

    @classmethod
    def from_dict(cls, data: Dict) -> 'HealthCheckConfig':
        return cls(
            endpoint=data.get('endpoint', '/health'),
            interval_seconds=data.get('interval_seconds', 10),
            timeout_seconds=data.get('timeout_seconds', 5),
            retries=data.get('retries', 3)
        )

    def to_dict(self) -> Dict:
        return {
            'endpoint': self.endpoint,
            'interval_seconds': self.interval_seconds,
            'timeout_seconds': self.timeout_seconds,
            'retries': self.retries
        }


@dataclass
class DetectorManifest:
    name: str
    display_name: str
    version: str
    description: str
    repository: str
    category: str
    supported_input_types: List[str]
    multi_person: bool
    requires_gpu: bool
    port: int
    internal_port: int = 5000

    docker: DockerConfig = field(default_factory=DockerConfig)
    model_info: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    resource_profile: Dict[str, Any] = field(default_factory=dict)
    startup_time_seconds: int = 30
    timeout_seconds: int = 600
    health_check: HealthCheckConfig = field(default_factory=HealthCheckConfig)
    repo_pattern: str = 'clean_wrapper'
    patches_doc: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, manifest_path: str) -> 'DetectorManifest':
        if not os.path.exists(manifest_path):
            raise FileNotFoundError(f'Manifest not found: {manifest_path}')

        with open(manifest_path, 'r') as f:
            data = json.load(f)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict) -> 'DetectorManifest':
        docker = DockerConfig.from_dict(data.get('docker', {}))
        health_check = HealthCheckConfig.from_dict(data.get('health_check', {}))

        return cls(
            name=data['name'],
            display_name=data['display_name'],
            version=data['version'],
            description=data['description'],
            repository=data['repository'],
            category=data['category'],
            supported_input_types=data['supported_input_types'],
            multi_person=data['multi_person'],
            requires_gpu=data['requires_gpu'],
            port=data['port'],
            internal_port=data.get('internal_port', 5000),
            docker=docker,
            model_info=data.get('model_info', {}),
            outputs=data.get('outputs', {}),
            config_schema=data.get('config_schema', {}),
            resource_profile=data.get('resource_profile', {}),
            startup_time_seconds=data.get('startup_time_seconds', 30),
            timeout_seconds=data.get('timeout_seconds', 600),
            health_check=health_check,
            repo_pattern=data.get('repo_pattern', 'clean_wrapper'),
            patches_doc=data.get('patches_doc'),
            tags=data.get('tags', []),
            metadata=data.get('metadata', {})
        )

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'display_name': self.display_name,
            'version': self.version,
            'description': self.description,
            'repository': self.repository,
            'category': self.category,
            'supported_input_types': self.supported_input_types,
            'multi_person': self.multi_person,
            'requires_gpu': self.requires_gpu,
            'port': self.port,
            'internal_port': self.internal_port,
            'docker': self.docker.to_dict(),
            'model_info': self.model_info,
            'outputs': self.outputs,
            'config_schema': self.config_schema,
            'resource_profile': self.resource_profile,
            'startup_time_seconds': self.startup_time_seconds,
            'timeout_seconds': self.timeout_seconds,
            'health_check': self.health_check.to_dict(),
            'repo_pattern': self.repo_pattern,
            'patches_doc': self.patches_doc,
            'tags': self.tags,
            'metadata': self.metadata
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, filepath: str) -> None:
        with open(filepath, 'w') as f:
            f.write(self.to_json())
