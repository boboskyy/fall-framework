
import io
import threading

from flask import Flask, request, jsonify
from flask_cors import CORS

from gateway.registry import DetectorRegistry
from gateway.orchestrator import Orchestrator
from gateway.comparison_engine import ComparisonEngine
from gateway.batch_manager import BatchManager
from gateway.build_manager import BuildManager
from gateway.download_manager import DownloadManager
from gateway.file_manager import FileManager
from gateway.template_engine import get_template_info, generate_template_zip
from gateway.dataset_manager import DatasetManager
from gateway.evaluation_manager import EvaluationManager


def create_gateway_app():
    app = Flask(__name__)
    CORS(app)

    registry = DetectorRegistry()
    registry.scan_manifests()
    orchestrator = Orchestrator(registry)
    comparison_engine = ComparisonEngine()
    file_manager = FileManager()
    batch_manager = BatchManager(orchestrator, file_manager)
    build_manager = BuildManager(registry)
    download_manager = DownloadManager(registry)

    import os
    dataset_registry_url = os.environ.get('FALLFW_DATASET_REGISTRY_URL', '')
    dataset_manager = DatasetManager(
        datasets_dir='/datasets',
        shared_dir='/shared',
        registry_url=dataset_registry_url,
    )
    evaluation_manager = EvaluationManager(
        dataset_manager=dataset_manager,
        orchestrator=orchestrator,
        comparison_engine=comparison_engine,
    )


    @app.route('/api/v1/detectors', methods=['GET'])
    def list_detectors():
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        detectors = registry.get_all_detectors(refresh_health=refresh)

        return jsonify({
            'detectors': [d.to_dict() for d in detectors],
            'count': len(detectors)
        })

    @app.route('/api/v1/detectors/<name>', methods=['GET'])
    def get_detector_info(name):
        detector = registry.get_detector(name)
        if not detector:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Detector "{name}" not found'
            }), 404

        manifest = registry.get_manifest(name)

        return jsonify({
            'detector': detector.to_dict(),
            'manifest': manifest
        })

    @app.route('/api/v1/detectors/<name>/health', methods=['GET'])
    def check_detector_health(name):
        result = registry.check_health(name)

        if result['status'] == 'not_found':
            return jsonify(result), 404
        elif result['status'] in ('unhealthy', 'error', 'stopped', 'not_built',
                                   'not_downloaded', 'downloading', 'building'):
            return jsonify(result), 503

        return jsonify(result)

    @app.route('/api/v1/detectors/summary', methods=['GET'])
    def get_detectors_summary():
        detectors = registry.get_all_detectors()
        names = [d.name for d in detectors]
        return jsonify(evaluation_manager.get_all_detectors_summary(names))

    @app.route('/api/v1/detectors/<name>/stats', methods=['GET'])
    def get_detector_stats(name):
        detector = registry.get_detector(name)
        if not detector:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Detector "{name}" not found',
            }), 404
        return jsonify(evaluation_manager.get_detector_stats(name))

    @app.route('/api/v1/detectors/<name>/start', methods=['POST'])
    def start_detector(name):
        result = registry.start_container(name)

        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error') in ('NOT_DOWNLOADED', 'GPU_UNAVAILABLE'):
            return jsonify(result), 400
        elif result.get('error'):
            return jsonify(result), 500

        return jsonify(result)

    @app.route('/api/v1/detectors/<name>/stop', methods=['POST'])
    def stop_detector(name):
        result = registry.stop_container(name)

        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error'):
            return jsonify(result), 500

        return jsonify(result)

    @app.route('/api/v1/detectors/rescan', methods=['POST'])
    def rescan_detectors():
        result = registry.rescan_manifests()
        return jsonify(result)

    @app.route('/api/v1/detectors/<name>/uninstall', methods=['DELETE'])
    def uninstall_detector(name):
        result = registry.uninstall_container(name)

        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error'):
            return jsonify(result), 500

        return jsonify(result)


    @app.route('/api/v1/detectors/<name>/build', methods=['POST'])
    def build_detector(name):
        device = 'cpu'
        if request.is_json and request.get_json():
            device = request.get_json().get('device', 'cpu')

        result = build_manager.submit_build(name, device=device)

        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error') == 'NOT_DOWNLOADED':
            return jsonify(result), 400
        elif result.get('error') == 'ALREADY_BUILDING':
            return jsonify(result), 409
        elif result.get('error') in ('GPU_NOT_SUPPORTED', 'INVALID_PARAMETER'):
            return jsonify(result), 400
        elif result.get('error'):
            return jsonify(result), 500

        return jsonify(result), 202

    @app.route('/api/v1/builds/<build_id>', methods=['GET'])
    def get_build_status(build_id):
        build = build_manager.get_build(build_id)
        if not build:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Build "{build_id}" not found'
            }), 404

        return jsonify(build.get_summary())

    @app.route('/api/v1/builds', methods=['GET'])
    def list_builds():
        builds = build_manager.list_builds()
        return jsonify({
            'builds': builds,
            'count': len(builds)
        })


    @app.route('/api/v1/detectors/<name>/download', methods=['POST'])
    def download_detector(name):
        force = False
        if request.is_json and request.get_json():
            force = request.get_json().get('force', False)

        result = download_manager.submit_download(name, force=force)

        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error') in ('ALREADY_DOWNLOADING', 'ALREADY_DOWNLOADED'):
            return jsonify(result), 409
        elif result.get('error'):
            return jsonify(result), 500

        return jsonify(result), 202

    @app.route('/api/v1/detectors/<name>/download', methods=['DELETE'])
    def delete_download(name):
        result = download_manager.delete_download(name)

        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error'):
            return jsonify(result), 500

        return jsonify(result)

    @app.route('/api/v1/downloads/<download_id>', methods=['GET'])
    def get_download_status(download_id):
        download = download_manager.get_download(download_id)
        if not download:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Download "{download_id}" not found'
            }), 404

        return jsonify(download.get_summary())

    @app.route('/api/v1/downloads', methods=['GET'])
    def list_downloads():
        downloads = download_manager.list_downloads()
        return jsonify({
            'downloads': downloads,
            'count': len(downloads)
        })


    @app.route('/api/v1/template', methods=['GET'])
    def get_template():
        name = request.args.get('name')
        if not name:
            return jsonify({
                'error': 'MISSING_PARAMETER',
                'message': 'Query parameter "name" is required. '
                           'Example: /api/v1/template?name=my_fall_detector'
            }), 400

        category = request.args.get('category', 'object_detection')
        input_type = request.args.get('input_type', 'video')

        try:
            zip_bytes = generate_template_zip(
                detector_name=name,
                category=category,
                input_type=input_type,
            )
        except ValueError as e:
            return jsonify({
                'error': 'INVALID_PARAMETER',
                'message': str(e)
            }), 400

        from flask import send_file
        return send_file(
            io.BytesIO(zip_bytes),
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{name}.zip',
        )

    @app.route('/api/v1/template/info', methods=['GET'])
    def template_info():
        info = get_template_info()
        return jsonify(info)

    @app.route('/api/v1/health', methods=['GET'])
    def gateway_health():
        registry.refresh_all_health()
        detectors = registry.get_all_detectors()

        healthy_count = sum(1 for d in detectors if d.container_status == 'healthy')
        stopped_count = sum(1 for d in detectors if d.container_status == 'stopped')
        not_built_count = sum(1 for d in detectors if d.container_status == 'not_built')
        not_downloaded_count = sum(1 for d in detectors if d.container_status == 'not_downloaded')
        building_count = sum(1 for d in detectors if d.container_status == 'building')
        downloading_count = sum(1 for d in detectors if d.container_status == 'downloading')
        unhealthy_count = sum(1 for d in detectors
                              if d.container_status in ('unhealthy', 'error'))

        return jsonify({
            'gateway': 'healthy',
            'detectors': {
                'total': len(detectors),
                'healthy': healthy_count,
                'stopped': stopped_count,
                'not_built': not_built_count,
                'not_downloaded': not_downloaded_count,
                'building': building_count,
                'downloading': downloading_count,
                'unhealthy': unhealthy_count
            },
            'status_details': [
                {
                    'name': d.name,
                    'status': d.container_status,
                    'last_check': d.last_health_check
                }
                for d in detectors
            ]
        })


    @app.route('/api/v1/upload', methods=['POST'])
    def upload_file():
        if 'file' not in request.files:
            return jsonify({
                'error': 'MISSING_FILE',
                'message': 'No file field in request. Use multipart/form-data with a "file" field.'
            }), 400

        uploaded_file = request.files['file']
        if not uploaded_file.filename:
            return jsonify({
                'error': 'EMPTY_FILENAME',
                'message': 'No file selected'
            }), 400

        absolute_path, relative_path = file_manager.save_uploaded_file(uploaded_file)
        file_info = file_manager.get_file_info(absolute_path)

        return jsonify({
            'filename': file_info['filename'],
            'input_path': relative_path,
            'size_mb': file_info['size_mb']
        })

    @app.route('/api/v1/files', methods=['GET'])
    def list_files():
        files = file_manager.list_files()
        return jsonify({
            'files': files,
            'count': len(files)
        })

    @app.route('/api/v1/stream', methods=['GET'])
    def stream_file():
        from flask import send_file as _send_file

        # ?filename= mode: search uploads then all datasets by bare filename
        filename_only = request.args.get('filename', '').replace('\\', '/').strip('/')
        if filename_only:
            if '..' in filename_only or '/' in filename_only:
                return jsonify({'error': 'Invalid filename'}), 400
            # 1. uploads
            candidate = str(file_manager.uploads_dir / filename_only)
            if os.path.isfile(candidate):
                return _send_file(candidate, conditional=True)
            # 2. walk all datasets
            if os.path.isdir('/datasets'):
                for root, _, files in os.walk('/datasets'):
                    if filename_only in files:
                        return _send_file(os.path.join(root, filename_only), conditional=True)
            return jsonify({'error': 'File not found'}), 404

        # ?path= mode: explicit prefix-based path
        path = request.args.get('path', '').replace('\\', '/').strip('/')
        if not path or '..' in path:
            return jsonify({'error': 'Invalid path'}), 400

        if path.startswith('datasets/'):
            full_path = os.path.join('/datasets', path[len('datasets/'):])
            if not os.path.isfile(full_path):
                parts = path[len('datasets/'):].split('/', 1)
                if len(parts) == 2:
                    dataset_dir = os.path.join('/datasets', parts[0])
                    fname = parts[1]
                    for root, _, files in os.walk(dataset_dir):
                        if fname in files:
                            full_path = os.path.join(root, fname)
                            break
        elif path.startswith('uploads/'):
            full_path = str(file_manager.uploads_dir / path[len('uploads/'):])
        else:
            return jsonify({'error': 'Invalid path prefix'}), 400

        if not os.path.isfile(full_path):
            return jsonify({'error': 'File not found'}), 404

        return _send_file(full_path, conditional=True)

    @app.route('/api/v1/files/<filename>', methods=['DELETE'])
    def delete_file(filename):
        file_path = str(file_manager.uploads_dir / filename)
        deleted = file_manager.delete_file(file_path)

        if not deleted:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'File "{filename}" not found'
            }), 404

        return jsonify({
            'message': f'File "{filename}" deleted',
            'filename': filename
        })


    @app.route('/api/v1/detect', methods=['POST'])
    def detect_async():
        data = request.get_json()

        if not data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body required'
            }), 400

        input_path = data.get('input_path')
        input_type = data.get('input_type', 'video')
        detector_name = data.get('detector')
        config = data.get('config', {})
        label = data.get('label')

        if not input_path or not detector_name:
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: input_path, detector'
            }), 400

        result = orchestrator.submit_single(
            input_path=input_path,
            input_type=input_type,
            detector_name=detector_name,
            config=config,
            sync=False,
            label=label
        )

        if result.get('error'):
            return jsonify(result), 400

        return jsonify(result), 202

    @app.route('/api/v1/detect/sync', methods=['POST'])
    def detect_sync():
        data = request.get_json()

        if not data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body required'
            }), 400

        input_path = data.get('input_path')
        input_type = data.get('input_type', 'video')
        detector_name = data.get('detector')
        config = data.get('config', {})
        label = data.get('label')

        if not input_path or not detector_name:
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: input_path, detector'
            }), 400

        result = orchestrator.submit_single(
            input_path=input_path,
            input_type=input_type,
            detector_name=detector_name,
            config=config,
            sync=True,
            label=label
        )

        if result.get('error'):
            status_code = 503 if 'not healthy' in result.get('message', '').lower() else 400
            return jsonify(result), status_code

        if result.get('status') == 'failed':
            return jsonify(result), 500

        return jsonify(result)

    @app.route('/api/v1/detect/multi', methods=['POST'])
    def detect_multi():
        data = request.get_json()

        if not data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body required'
            }), 400

        input_path = data.get('input_path')
        input_type = data.get('input_type', 'video')
        detector_names = data.get('detectors', [])
        config = data.get('config', {})
        sync = data.get('sync', False)
        label = data.get('label')

        if not input_path:
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: input_path'
            }), 400

        if not detector_names or not isinstance(detector_names, list):
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: detectors (array of detector names)'
            }), 400

        if len(detector_names) == 0:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'At least one detector required'
            }), 400

        result = orchestrator.submit_multi(
            input_path=input_path,
            input_type=input_type,
            detector_names=detector_names,
            config=config,
            sync=sync,
            label=label
        )

        if result.get('error'):
            status_code = 503 if 'not healthy' in result.get('message', '').lower() else 400
            return jsonify(result), status_code

        if result.get('status') == 'failed':
            return jsonify(result), 500

        status_code = 200 if sync else 202
        return jsonify(result), status_code


    @app.route('/api/v1/jobs/<job_id>', methods=['GET'])
    def get_job_status(job_id):
        status = orchestrator.get_job_status(job_id)

        if not status:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Job "{job_id}" not found'
            }), 404

        return jsonify(status)

    @app.route('/api/v1/jobs/<job_id>/results', methods=['GET'])
    def get_job_results(job_id):
        results = orchestrator.get_job_results(job_id)

        if not results:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Job "{job_id}" not found'
            }), 404

        return jsonify(results)

    @app.route('/api/v1/jobs', methods=['GET'])
    def list_jobs():
        jobs = orchestrator.list_jobs()
        return jsonify({
            'jobs': jobs,
            'count': len(jobs)
        })


    @app.route('/api/v1/label/<id>', methods=['PATCH'])
    def set_label(id):
        data = request.get_json()
        if not data or 'label' not in data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body with "label" field required'
            }), 400

        new_label = data['label']

        if id.startswith('b-'):
            obj = batch_manager.get_batch(id)
        elif id.startswith('c-'):
            obj = comparison_engine.get_comparison(id)
        else:
            obj = orchestrator.get_job(id)

        if not obj:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'ID "{id}" not found'
            }), 404

        obj.label = new_label
        return jsonify({'id': id, 'label': new_label})


    @app.route('/api/v1/compare', methods=['POST'])
    def compare():
        data = request.get_json()

        if not data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body required'
            }), 400

        input_path = data.get('input_path')
        input_type = data.get('input_type', 'video')
        detector_names = data.get('detectors', [])
        config = data.get('config', {})
        sync = data.get('sync', False)
        label = data.get('label')

        if not input_path:
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: input_path'
            }), 400

        if not detector_names or not isinstance(detector_names, list):
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: detectors (array of detector names)'
            }), 400

        if len(detector_names) < 2:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'At least 2 detectors required for comparison'
            }), 400

        input_file = input_path.split('/')[-1]

        if sync:
            return _compare_sync(
                orchestrator, comparison_engine,
                input_path, input_type, input_file, detector_names, config,
                label=label
            )
        else:
            comparison_job = comparison_engine.create_comparison_job(
                job_id='',
                detectors=detector_names,
                input_file=input_file,
                input_type=input_type,
                label=label
            )

            thread = threading.Thread(
                target=_run_compare_async,
                args=(orchestrator, comparison_engine, comparison_job.comparison_id,
                      input_path, input_type, detector_names, config),
                daemon=True
            )
            thread.start()

            return jsonify({
                'comparison_id': comparison_job.comparison_id,
                'label': comparison_job.label,
                'status': 'running',
                'detectors': detector_names,
                'input_file': input_file,
                'created_at': comparison_job.created_at,
                'message': f'Comparison started. Poll GET /api/v1/compare/{comparison_job.comparison_id} for results.'
            }), 202

    @app.route('/api/v1/compare/<comparison_id>', methods=['GET'])
    def get_comparison(comparison_id):
        comparison_job = comparison_engine.get_comparison(comparison_id)

        if not comparison_job:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Comparison "{comparison_id}" not found'
            }), 404

        return jsonify(comparison_job.get_summary())

    @app.route('/api/v1/comparisons', methods=['GET'])
    def list_comparisons():
        comparisons = comparison_engine.list_comparisons()
        return jsonify({
            'comparisons': comparisons,
            'count': len(comparisons)
        })


    @app.route('/api/v1/batch/detect', methods=['POST'])
    def batch_detect():
        data = request.get_json()

        if not data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body required'
            }), 400

        zip_path = data.get('zip_path')
        detector_names = data.get('detectors', [])
        input_type = data.get('input_type', 'video')
        config = data.get('config', {})
        sync = data.get('sync', False)
        label = data.get('label')

        if not zip_path:
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: zip_path'
            }), 400

        if not detector_names or not isinstance(detector_names, list):
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: detectors (array of detector names)'
            }), 400

        if len(detector_names) == 0:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'At least one detector required'
            }), 400

        try:
            batch = batch_manager.create_batch(
                zip_path=zip_path,
                detector_names=detector_names,
                input_type=input_type,
                config=config,
                label=label
            )
        except ValueError as e:
            return jsonify({
                'error': 'BATCH_CREATION_FAILED',
                'message': str(e)
            }), 400

        if sync:
            try:
                batch = batch_manager.start_batch(batch.batch_id)
                return jsonify({
                    'batch_id': batch.batch_id,
                    'label': batch.label,
                    'status': batch.status,
                    'total_files': len(batch.input_files),
                    'total_detectors': len(batch.detector_names),
                    'total_tasks': len(batch.input_files) * len(batch.detector_names),
                    'created_at': batch.created_at,
                    'completed_at': batch.completed_at,
                    'message': f'Batch complete. GET /api/v1/batch/{batch.batch_id}/results for full results.'
                })
            except Exception as e:
                return jsonify({
                    'error': 'BATCH_FAILED',
                    'message': str(e)
                }), 500
        else:
            thread = threading.Thread(
                target=_run_batch_async,
                args=(batch_manager, batch.batch_id),
                daemon=True
            )
            thread.start()

            return jsonify({
                'batch_id': batch.batch_id,
                'label': batch.label,
                'status': 'running',
                'total_files': len(batch.input_files),
                'total_detectors': len(batch.detector_names),
                'total_tasks': len(batch.input_files) * len(batch.detector_names),
                'created_at': batch.created_at,
                'message': f'Batch processing started. Poll GET /api/v1/batch/{batch.batch_id}/status for progress.'
            }), 202

    @app.route('/api/v1/batch/<batch_id>/status', methods=['GET'])
    def get_batch_status(batch_id):
        status = batch_manager.get_batch_status(batch_id)

        if not status:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Batch "{batch_id}" not found'
            }), 404

        return jsonify(status)

    @app.route('/api/v1/batch/<batch_id>/results', methods=['GET'])
    def get_batch_results(batch_id):
        results = batch_manager.get_batch_results(batch_id)

        if not results:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Batch "{batch_id}" not found'
            }), 404

        return jsonify(results)

    @app.route('/api/v1/batches', methods=['GET'])
    def list_batches():
        batches = batch_manager.list_batches()
        return jsonify({
            'batches': batches,
            'count': len(batches)
        })


    # === Dataset Management ===

    @app.route('/api/v1/datasets', methods=['GET'])
    def list_datasets():
        datasets = dataset_manager.list_datasets()
        return jsonify({
            'datasets': datasets,
            'count': len(datasets),
        })

    @app.route('/api/v1/datasets/<name>', methods=['GET'])
    def get_dataset_info(name):
        info = dataset_manager.get_dataset_info(name)
        if not info:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Dataset "{name}" not found',
            }), 404
        return jsonify(info)

    @app.route('/api/v1/datasets/<name>/files', methods=['GET'])
    def get_dataset_files(name):
        label = request.args.get('label')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))

        result = dataset_manager.get_dataset_files(name, label=label,
                                                   page=page, per_page=per_page)
        if not result:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Dataset "{name}" not found',
            }), 404
        return jsonify(result)

    @app.route('/api/v1/datasets/<name>/download', methods=['POST'])
    def download_dataset(name):
        result = dataset_manager.download_dataset(name)
        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error') in ('ALREADY_DOWNLOADED', 'ALREADY_DOWNLOADING'):
            return jsonify(result), 409
        elif result.get('error'):
            return jsonify(result), 500
        return jsonify(result), 202

    @app.route('/api/v1/datasets/<name>/download/status', methods=['GET'])
    def get_dataset_download_status(name):
        for dl in dataset_manager._downloads.values():
            if dl.dataset_name == name:
                return jsonify(dl.get_summary())
        return jsonify({
            'error': 'NOT_FOUND',
            'message': f'No download found for dataset "{name}"',
        }), 404

    @app.route('/api/v1/datasets/<name>', methods=['DELETE'])
    def delete_dataset(name):
        result = dataset_manager.delete_dataset(name)
        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        return jsonify(result)

    @app.route('/api/v1/datasets/<name>/copy-to-files', methods=['POST'])
    def copy_dataset_files_to_uploads(name):
        data = request.get_json(force=True, silent=True)
        if not data or not data.get('filenames'):
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: filenames (array of file names)',
            }), 400

        result = dataset_manager.copy_to_uploads(name, data['filenames'])
        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        return jsonify(result)

    @app.route('/api/v1/datasets/upload', methods=['POST'])
    def upload_dataset():
        if 'file' not in request.files:
            return jsonify({
                'error': 'MISSING_FILE',
                'message': 'No file field in request. Use multipart/form-data with a "file" field.',
            }), 400

        uploaded_file = request.files['file']
        if not uploaded_file.filename:
            return jsonify({
                'error': 'EMPTY_FILENAME',
                'message': 'No file selected',
            }), 400

        import tempfile, os
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.zip')
        os.close(tmp_fd)
        try:
            uploaded_file.save(tmp_path)
            ds_name = request.form.get('name')
            display_name = request.form.get('display_name')
            result = dataset_manager.upload_dataset(tmp_path, name=ds_name,
                                                    display_name=display_name)
            if result.get('error'):
                return jsonify(result), 400
            return jsonify(result), 201
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @app.route('/api/v1/datasets/refresh-registry', methods=['POST'])
    def refresh_dataset_registry():
        result = dataset_manager.refresh_registry()
        return jsonify(result)

    # === Dataset Labeling ===

    @app.route('/api/v1/datasets/<name>/files/<filename>', methods=['PATCH'])
    def label_dataset_file(name, filename):
        data = request.get_json()
        if not data or 'label' not in data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body with "label" field required',
            }), 400

        result = dataset_manager.label_file(name, filename, data['label'])
        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error'):
            return jsonify(result), 400
        return jsonify(result)

    @app.route('/api/v1/datasets/<name>/labels', methods=['POST'])
    def bulk_label_dataset(name):
        data = request.get_json()
        if not data or 'labels' not in data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body with "labels" field required',
            }), 400

        result = dataset_manager.bulk_label(name, data['labels'])
        if result.get('error') == 'NOT_FOUND':
            return jsonify(result), 404
        elif result.get('error'):
            return jsonify(result), 400
        return jsonify(result)

    # === Evaluation ===

    @app.route('/api/v1/evaluate', methods=['POST'])
    def start_evaluation():
        data = request.get_json()
        if not data:
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'JSON body required',
            }), 400

        dataset_name = data.get('dataset_name') or data.get('dataset')
        detector_names = data.get('detector_names') or data.get('detectors', [])

        if not dataset_name:
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: dataset_name',
            }), 400

        if not detector_names or not isinstance(detector_names, list):
            return jsonify({
                'error': 'MISSING_PARAMETERS',
                'message': 'Required: detector_names (array of detector names)',
            }), 400

        result = evaluation_manager.create_evaluation(
            dataset_name=dataset_name,
            detector_names=detector_names,
            selected_files=data.get('selected_files'),
            config=data.get('detector_configs') or data.get('config'),
            verdict_config=data.get('verdict_config'),
            sync=data.get('sync', False),
        )

        if result.get('error'):
            status_code = 404 if result['error'] == 'NOT_FOUND' else 400
            return jsonify(result), status_code

        status_code = 200 if data.get('sync', False) else 202
        return jsonify(result), status_code

    @app.route('/api/v1/evaluate/<eval_id>/status', methods=['GET'])
    def get_evaluation_status(eval_id):
        status = evaluation_manager.get_evaluation_status(eval_id)
        if not status:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Evaluation "{eval_id}" not found',
            }), 404
        return jsonify(status)

    @app.route('/api/v1/evaluate/<eval_id>/progress', methods=['GET'])
    def get_evaluation_progress(eval_id):
        # Per-detector live progress for the redesigned UI cockpit.
        prog = evaluation_manager.get_evaluation_progress(eval_id)
        if not prog:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Evaluation "{eval_id}" not found',
            }), 404
        return jsonify(prog)

    @app.route('/api/v1/evaluate/<eval_id>/stream', methods=['GET'])
    def stream_evaluation(eval_id):
        # Server-Sent Events live channel. One-way server→client progress push;
        # the frontend falls back to /status + /progress polling if absent.
        from flask import Response, stream_with_context
        gen = evaluation_manager.stream_evaluation(eval_id)
        if gen is None:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Evaluation "{eval_id}" not found',
            }), 404
        return Response(
            stream_with_context(gen()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            },
        )

    @app.route('/api/v1/evaluate/<eval_id>/cancel', methods=['POST'])
    def cancel_evaluation(eval_id):
        result = evaluation_manager.cancel_evaluation(eval_id)
        if 'error' in result:
            status_code = 404 if result['error'] == 'NOT_FOUND' else 409
            return jsonify(result), status_code
        return jsonify(result)

    @app.route('/api/v1/evaluate/<eval_id>/results', methods=['GET'])
    def get_evaluation_results(eval_id):
        results = evaluation_manager.get_evaluation_results(eval_id)
        if not results:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Evaluation "{eval_id}" not found',
            }), 404
        return jsonify(results)

    @app.route('/api/v1/evaluate/<eval_id>/export', methods=['GET'])
    def export_evaluation(eval_id):
        fmt = request.args.get('format', 'json')
        result = evaluation_manager.export_results(eval_id, fmt=fmt)
        if not result:
            return jsonify({
                'error': 'NOT_FOUND',
                'message': f'Evaluation "{eval_id}" not found or not completed',
            }), 404

        if fmt == 'csv':
            from flask import Response
            return Response(
                result['data'],
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=evaluation_{eval_id}.csv'},
            )
        return jsonify(result['data'])

    @app.route('/api/v1/evaluations', methods=['GET'])
    def list_evaluations():
        evaluations = evaluation_manager.list_evaluations()
        return jsonify({
            'evaluations': evaluations,
            'count': len(evaluations),
        })

    @app.route('/api/v1/evaluate/import', methods=['POST'])
    def import_evaluation():
        # Rebuild a completed evaluation 1:1 from exported per-clip rows
        # (filename, ground_truth, verdict, classification, confidence,
        #  fall_frames, total_frames, processing_time_ms). Persists to disk.
        data = request.get_json(silent=True)
        if not data or not data.get('dataset') or not data.get('detector') \
                or not isinstance(data.get('rows'), list):
            return jsonify({
                'error': 'INVALID_REQUEST',
                'message': 'Required: dataset, detector, rows (array of per-clip rows)',
            }), 400
        result = evaluation_manager.import_evaluation(
            dataset_name=data['dataset'],
            detector_name=data['detector'],
            rows=data['rows'],
            verdict_config=data.get('verdict_config'),
            eval_id=data.get('eval_id'),
            created_at=data.get('created_at'),
            completed_at=data.get('completed_at'),
        )
        return jsonify(result), 201


    @app.route('/', methods=['GET'])
    def root():
        return jsonify({
            'service': 'Fall Detection Framework Gateway',
            'version': '2.0.0',
            'status': 'running',
            'endpoints': {
                'upload': '/api/v1/upload',
                'files': '/api/v1/files',
                'detectors': '/api/v1/detectors',
                'detector_rescan': '/api/v1/detectors/rescan',
                'detector_download': '/api/v1/detectors/{name}/download',
                'detector_start': '/api/v1/detectors/{name}/start',
                'detector_stop': '/api/v1/detectors/{name}/stop',
                'detector_uninstall': '/api/v1/detectors/{name}/uninstall',
                'detector_build': '/api/v1/detectors/{name}/build',
                'downloads': '/api/v1/downloads',
                'builds': '/api/v1/builds',
                'template_download': '/api/v1/template?name={name}',
                'template_info': '/api/v1/template/info',
                'health': '/api/v1/health',
                'detect': '/api/v1/detect',
                'detect_sync': '/api/v1/detect/sync',
                'detect_multi': '/api/v1/detect/multi',
                'jobs': '/api/v1/jobs',
                'compare': '/api/v1/compare',
                'comparisons': '/api/v1/comparisons',
                'batch_detect': '/api/v1/batch/detect',
                'batches': '/api/v1/batches',
                'datasets': '/api/v1/datasets',
                'dataset_files': '/api/v1/datasets/{name}/files',
                'dataset_download': '/api/v1/datasets/{name}/download',
                'dataset_upload': '/api/v1/datasets/upload',
                'dataset_labels': '/api/v1/datasets/{name}/labels',
                'evaluate': '/api/v1/evaluate',
                'evaluations': '/api/v1/evaluations'
            }
        })


    def _compare_sync(orch, comp_engine, input_path, input_type,
                       input_file, detector_names, config, label=None):
        job_result = orch.submit_multi(
            input_path=input_path,
            input_type=input_type,
            detector_names=detector_names,
            config=config,
            sync=True
        )

        if job_result.get('error'):
            return jsonify(job_result), 400

        if job_result.get('status') == 'failed':
            return jsonify({
                'error': 'DETECTION_FAILED',
                'message': 'All detectors failed',
                'job_result': job_result
            }), 500

        comparison_job = comp_engine.create_comparison_job(
            job_id=job_result['job_id'],
            detectors=detector_names,
            input_file=input_file,
            input_type=input_type,
            label=label
        )

        try:
            detector_results = job_result.get('results', {})
            successful_results = {
                name: result for name, result in detector_results.items()
                if result is not None
            }

            if len(successful_results) < 2:
                return jsonify({
                    'error': 'INSUFFICIENT_RESULTS',
                    'message': 'At least 2 detectors must succeed for comparison',
                    'job_result': job_result
                }), 400

            comp_engine.compare_results(
                comparison_id=comparison_job.comparison_id,
                detector_results=successful_results
            )

            return jsonify({
                'comparison_id': comparison_job.comparison_id,
                'label': comparison_job.label,
                'job_id': comparison_job.job_id,
                'status': 'completed',
                'detectors': comparison_job.detectors,
                'input_file': input_file,
                'created_at': comparison_job.created_at,
                'completed_at': comparison_job.completed_at,
                'message': f'Comparison complete. Results at GET /api/v1/compare/{comparison_job.comparison_id}'
            })

        except Exception as e:
            return jsonify({
                'error': 'COMPARISON_FAILED',
                'message': str(e),
                'job_id': job_result['job_id']
            }), 500

    def _run_batch_async(bm, batch_id):
        try:
            bm.start_batch(batch_id)
        except Exception:
            pass

    def _run_compare_async(orch, comp_engine, comparison_id,
                           input_path, input_type, detector_names, config):
        try:
            job_result = orch.submit_multi(
                input_path=input_path,
                input_type=input_type,
                detector_names=detector_names,
                config=config,
                sync=True
            )

            if 'error' in job_result or job_result.get('status') == 'failed':
                comp_engine.fail_comparison(
                    comparison_id,
                    error=job_result.get('message', 'Detection failed')
                )
                return

            comp_engine.update_job_id(comparison_id, job_result['job_id'])

            detector_results = job_result.get('results', {})
            successful_results = {
                name: result for name, result in detector_results.items()
                if result is not None
            }

            if len(successful_results) < 2:
                comp_engine.fail_comparison(
                    comparison_id,
                    error='Fewer than 2 detectors succeeded'
                )
                return

            comp_engine.compare_results(
                comparison_id=comparison_id,
                detector_results=successful_results
            )
        except Exception as e:
            comp_engine.fail_comparison(comparison_id, error=str(e))

    return app


if __name__ == '__main__':
    app = create_gateway_app()
    app.run(host='0.0.0.0', port=5000, debug=False)
