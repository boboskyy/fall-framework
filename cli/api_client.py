
import time

import requests

from cli.constants import (
    GATEWAY_URL, REQUEST_TIMEOUT, UPLOAD_TIMEOUT,
    DETECT_SYNC_TIMEOUT, POLL_INTERVAL
)


class GatewayError(Exception):

    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class GatewayClient:

    def __init__(self, base_url=None):
        self.base_url = (base_url or GATEWAY_URL).rstrip('/')
        self.api = f'{self.base_url}/api/v1'

    def _request(self, method, path, timeout=REQUEST_TIMEOUT, **kwargs):
        url = f'{self.api}{path}'
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.ConnectionError:
            raise GatewayError(
                f'Cannot connect to gateway at {self.base_url}. '
                'Is the gateway running? (docker compose up gateway)'
            )
        except requests.Timeout:
            raise GatewayError(f'Request to {path} timed out after {timeout}s')

        data = None
        try:
            data = resp.json()
        except ValueError:
            pass

        if resp.status_code >= 400:
            msg = 'Request failed'
            if data:
                if data.get('message'):
                    msg = data['message']
                elif data.get('error'):
                    msg = f'{data["error"]}: {data.get("message", "")}'
            raise GatewayError(msg, status_code=resp.status_code, response_data=data)

        return data


    def is_reachable(self):
        try:
            self._request('GET', '/health', timeout=5)
            return True
        except GatewayError:
            return False

    def health(self):
        return self._request('GET', '/health')

    def detector_health(self, name):
        return self._request('GET', f'/detectors/{name}/health')


    def list_detectors(self, refresh=False):
        params = {'refresh': 'true'} if refresh else {}
        return self._request('GET', '/detectors', params=params)

    def get_detector(self, name):
        return self._request('GET', f'/detectors/{name}')


    def upload_file(self, file_path):
        with open(file_path, 'rb') as f:
            files = {'file': (file_path.split('/')[-1], f)}
            return self._request(
                'POST', '/upload',
                files=files,
                timeout=UPLOAD_TIMEOUT
            )

    def list_files(self):
        return self._request('GET', '/files')

    def delete_file(self, filename):
        return self._request('DELETE', f'/files/{filename}')


    def detect_async(self, input_path, detector, input_type='video', config=None, label=None):
        payload = {
            'input_path': input_path,
            'input_type': input_type,
            'detector': detector,
            'config': config or {}
        }
        if label:
            payload['label'] = label
        return self._request('POST', '/detect', json=payload)

    def detect_sync(self, input_path, detector, input_type='video', config=None, label=None):
        payload = {
            'input_path': input_path,
            'input_type': input_type,
            'detector': detector,
            'config': config or {}
        }
        if label:
            payload['label'] = label
        return self._request('POST', '/detect/sync', json=payload, timeout=DETECT_SYNC_TIMEOUT)

    def detect_multi(self, input_path, detectors, input_type='video',
                     config=None, sync=False, label=None):
        timeout = DETECT_SYNC_TIMEOUT if sync else REQUEST_TIMEOUT
        payload = {
            'input_path': input_path,
            'input_type': input_type,
            'detectors': detectors,
            'config': config or {},
            'sync': sync
        }
        if label:
            payload['label'] = label
        return self._request('POST', '/detect/multi', json=payload, timeout=timeout)


    def compare(self, input_path, detectors, input_type='video',
                config=None, sync=False, label=None):
        timeout = DETECT_SYNC_TIMEOUT if sync else REQUEST_TIMEOUT
        payload = {
            'input_path': input_path,
            'input_type': input_type,
            'detectors': detectors,
            'config': config or {},
            'sync': sync
        }
        if label:
            payload['label'] = label
        return self._request('POST', '/compare', json=payload, timeout=timeout)

    def get_comparison(self, comparison_id):
        return self._request('GET', f'/compare/{comparison_id}')

    def list_comparisons(self):
        return self._request('GET', '/comparisons')


    def batch_detect(self, zip_path, detectors, input_type='video',
                     config=None, sync=False, label=None):
        timeout = DETECT_SYNC_TIMEOUT if sync else REQUEST_TIMEOUT
        payload = {
            'zip_path': zip_path,
            'detectors': detectors,
            'input_type': input_type,
            'config': config or {},
            'sync': sync
        }
        if label:
            payload['label'] = label
        return self._request('POST', '/batch/detect', json=payload, timeout=timeout)

    def get_batch_status(self, batch_id):
        return self._request('GET', f'/batch/{batch_id}/status')

    def get_batch_results(self, batch_id):
        return self._request('GET', f'/batch/{batch_id}/results')

    def list_batches(self):
        return self._request('GET', '/batches')


    def set_label(self, id, label):
        return self._request('PATCH', f'/label/{id}', json={'label': label})


    def get_job(self, job_id):
        return self._request('GET', f'/jobs/{job_id}')

    def get_job_results(self, job_id):
        return self._request('GET', f'/jobs/{job_id}/results')

    def list_jobs(self):
        return self._request('GET', '/jobs')


    def poll_job(self, job_id, callback=None):
        while True:
            status = self.get_job(job_id)
            current = status.get('status', 'unknown')

            if callback:
                callback(status)

            if current in ('completed', 'partial', 'failed', 'cancelled'):
                return self.get_job_results(job_id)

            time.sleep(POLL_INTERVAL)

    def poll_comparison(self, comparison_id, callback=None):
        while True:
            result = self.get_comparison(comparison_id)
            current = result.get('status', 'unknown')

            if callback:
                callback(result)

            if current in ('completed', 'failed'):
                return result

            time.sleep(POLL_INTERVAL)

    def poll_batch(self, batch_id, callback=None):
        while True:
            status = self.get_batch_status(batch_id)
            current = status.get('status', 'unknown')

            if callback:
                callback(status)

            if current in ('completed', 'partial', 'failed'):
                return self.get_batch_results(batch_id)

            time.sleep(POLL_INTERVAL)
