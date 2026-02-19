from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import os
import sys
import threading
import time
import traceback
from datetime import datetime

sys.path.insert(0, '/app')

from .models import (
    DetectionRequest,
    DetectionResponse,
    DetectionStatus,
    InputType
)
from .task_manager import TaskManager


def create_app(detector_class, config=None):
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = '/app/uploads'
    app.config['OUTPUT_FOLDER'] = '/app/outputs'
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

    task_manager = TaskManager()

    detector = detector_class(config)
    detector_initialized = False
    initialization_error = None

    try:
        detector.initialize()
        detector_initialized = True
    except Exception as e:
        initialization_error = str(e)
        print(f'ERROR: Failed to initialize detector {detector.name}: {e}')
        traceback.print_exc()

    def process_task(task_id, input_path, input_type, config):
        try:
            task_manager.set_processing(task_id)

            req = DetectionRequest(
                task_id=task_id,
                input_type=input_type,
                input_path=input_path,
                config=config
            )

            validation_error = detector.validate_request(req)
            if validation_error:
                task_manager.set_failed(task_id, validation_error)
                return

            start_time = time.time()
            response = detector.detect(req)
            processing_time = (time.time() - start_time) * 1000

            if response.processing_time_ms == 0:
                response.processing_time_ms = processing_time

            task_manager.set_completed(task_id, response)

        except Exception as e:
            error_msg = f'{type(e).__name__}: {str(e)}'
            print(f'ERROR in task {task_id}: {error_msg}')
            traceback.print_exc()
            task_manager.set_failed(task_id, error_msg)


    @app.route('/health', methods=['GET'])
    def health():
        if not detector_initialized:
            return jsonify({
                'status': 'unhealthy',
                'error': initialization_error or 'Detector not initialized',
                'detector': detector.name,
                'timestamp': datetime.utcnow().isoformat()
            }), 503

        return jsonify({
            'status': 'healthy',
            'detector': detector.get_info(),
            'model_loaded': detector._initialized,
            'timestamp': datetime.utcnow().isoformat()
        })

    @app.route('/info', methods=['GET'])
    def info():
        return jsonify(detector.get_info())

    @app.route('/detect', methods=['POST'])
    def detect():
        if not detector_initialized:
            return jsonify({
                'error': 'Detector not initialized',
                'details': initialization_error
            }), 503

        if request.content_type and 'multipart/form-data' in request.content_type:
            if 'file' not in request.files:
                return jsonify({'error': 'No file provided'}), 400

            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            config_param = {}
            if 'config' in request.form:
                import json
                config_param = json.loads(request.form['config'])

            ext = os.path.splitext(filename)[1].lower()
            if ext in ['.csv', '.tsv']:
                input_type = InputType.SENSOR_CSV
            else:
                input_type = InputType.VIDEO

        elif request.is_json:
            data = request.get_json()
            filepath = data.get('input_path')
            if not filepath:
                return jsonify({'error': 'input_path required in JSON body'}), 400

            if not os.path.exists(filepath):
                return jsonify({'error': f'File not found: {filepath}'}), 404

            config_param = data.get('config', {})

            if 'input_type' in data:
                input_type = InputType(data['input_type'])
            else:
                ext = os.path.splitext(filepath)[1].lower()
                input_type = InputType.SENSOR_CSV if ext in ['.csv', '.tsv'] else InputType.VIDEO

        else:
            return jsonify({'error': 'Content-Type must be multipart/form-data or application/json'}), 400

        req = DetectionRequest(
            input_type=input_type,
            input_path=filepath,
            config=config_param
        )

        validation_error = detector.validate_request(req)
        if validation_error:
            return jsonify({'error': validation_error, 'code': 'VALIDATION_FAILED'}), 400

        task_id = task_manager.create_task(req)

        thread = threading.Thread(
            target=process_task,
            args=(task_id, filepath, input_type, config_param),
            daemon=True
        )
        thread.start()

        return jsonify({
            'task_id': task_id,
            'status': 'pending',
            'message': 'Detection task created. Poll GET /task/{task_id} for status.'
        }), 202

    @app.route('/detect/sync', methods=['POST'])
    def detect_sync():
        if not detector_initialized:
            return jsonify({
                'error': 'Detector not initialized',
                'details': initialization_error
            }), 503

        if request.content_type and 'multipart/form-data' in request.content_type:
            if 'file' not in request.files:
                return jsonify({'error': 'No file provided'}), 400

            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            config_param = {}
            if 'config' in request.form:
                import json
                config_param = json.loads(request.form['config'])

            ext = os.path.splitext(filename)[1].lower()
            input_type = InputType.SENSOR_CSV if ext in ['.csv', '.tsv'] else InputType.VIDEO

        elif request.is_json:
            data = request.get_json()
            filepath = data.get('input_path')
            if not filepath:
                return jsonify({'error': 'input_path required in JSON body'}), 400

            if not os.path.exists(filepath):
                return jsonify({'error': f'File not found: {filepath}'}), 404

            config_param = data.get('config', {})

            if 'input_type' in data:
                input_type = InputType(data['input_type'])
            else:
                ext = os.path.splitext(filepath)[1].lower()
                input_type = InputType.SENSOR_CSV if ext in ['.csv', '.tsv'] else InputType.VIDEO

        else:
            return jsonify({'error': 'Content-Type must be multipart/form-data or application/json'}), 400

        req = DetectionRequest(
            input_type=input_type,
            input_path=filepath,
            config=config_param
        )

        validation_error = detector.validate_request(req)
        if validation_error:
            return jsonify({'error': validation_error, 'code': 'VALIDATION_FAILED'}), 400

        try:
            start_time = time.time()
            response = detector.detect(req)
            processing_time = (time.time() - start_time) * 1000

            if response.processing_time_ms == 0:
                response.processing_time_ms = processing_time

            return jsonify(response.to_dict())

        except Exception as e:
            error_msg = f'{type(e).__name__}: {str(e)}'
            print(f'ERROR in sync detection: {error_msg}')
            traceback.print_exc()
            return jsonify({'error': error_msg, 'code': 'DETECTION_FAILED'}), 500

    @app.route('/task/<task_id>', methods=['GET'])
    def get_task(task_id):
        task = task_manager.get_task(task_id)
        if task is None:
            return jsonify({'error': 'Task not found', 'code': 'TASK_NOT_FOUND'}), 404
        return jsonify(task.to_dict())

    @app.route('/task/<task_id>/status', methods=['GET'])
    def get_task_status(task_id):
        task = task_manager.get_task(task_id)
        if task is None:
            return jsonify({'error': 'Task not found', 'code': 'TASK_NOT_FOUND'}), 404

        status_data = {
            'task_id': task_id,
            'status': task.status.value,
        }

        if task.status == DetectionStatus.PROCESSING:
            status_data['processed_frames'] = task.processed_frames
            status_data['total_frames'] = task.total_frames
            if task.total_frames > 0:
                status_data['percentage'] = (task.processed_frames / task.total_frames * 100)

        return jsonify(status_data)

    @app.route('/task/<task_id>', methods=['DELETE'])
    def delete_task(task_id):
        if task_manager.delete_task(task_id):
            return jsonify({'message': 'Task deleted'})
        return jsonify({'error': 'Task not found', 'code': 'TASK_NOT_FOUND'}), 404

    @app.route('/tasks', methods=['GET'])
    def list_tasks():
        return jsonify(task_manager.list_tasks())

    return app


if __name__ == '__main__':
    print('This module should be imported, not run directly')
    print('Usage:')
    print('  from core.server import create_app')
    print('  from detector import MyDetector')
    print('  app = create_app(MyDetector)')
    print('  app.run(host="0.0.0.0", port=5000)')
