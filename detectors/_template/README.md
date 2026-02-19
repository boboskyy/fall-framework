# {{DISPLAY_NAME}}

> Auto-generated boilerplate for a Fall Detection Framework v2 detector.

## Quick Start

1. **Clone or copy your model's repo** into `repo/`:
   ```bash
   git clone https://github.com/your/repo.git repo/
   ```

2. **Edit `detector.py`** — implement the three key methods:
   - `initialize()` — load your model (weights, config, etc.)
   - `detect(request)` — process video frame-by-frame, return results
   - `cleanup()` — release resources

3. **Edit `manifest.json`** — fill in model metadata:
   - `description`, `github_url`
   - `model_info` (architecture, framework, weights file)
   - `outputs` (keypoints? bounding boxes? tracking IDs?)
   - `config_schema` (what parameters can users tune?)

4. **Edit `requirements.txt`** — add your model's Python dependencies.
   PyTorch CPU is already installed in the Dockerfile. If you use TensorFlow
   instead, update the Dockerfile accordingly.

5. **Edit `Dockerfile`** — adjust if needed (different Python version,
   system libraries, etc.). Most detectors work with the default.

6. **Build and test**:
   ```bash
   # Via CLI
   fallfw build {{DETECTOR_NAME}}
   fallfw start {{DETECTOR_NAME}}
   fallfw detect video.mp4 -d {{DETECTOR_NAME}} --sync

   # Or via API
   curl -X POST http://localhost:3000/api/v1/detectors/{{DETECTOR_NAME}}/build
   curl -X POST http://localhost:3000/api/v1/detectors/{{DETECTOR_NAME}}/start
   ```

7. **Add to `docker-compose.yml`** (optional, for docker-compose workflows):
   ```yaml
   {{SERVICE_NAME}}:
     build:
       context: .
       dockerfile: detectors/{{DETECTOR_NAME}}/Dockerfile
     ports:
       - "{{PORT}}:5000"
     volumes:
       - ./shared:/shared:ro
     environment:
       - FLASK_ENV=production
     networks:
       - fall-detection
     healthcheck:
       test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
       interval: 30s
       timeout: 10s
       retries: 3
       start_period: 20s
   ```

## Architecture

```
Framework calls:        Your code:

create_app(Class)
  -> __init__()         (BaseDetector handles this)
  -> initialize()  -->  Load model, set thresholds

POST /detect/sync
  -> detect(req)   -->  Frame loop, run model, build results
  -> _build_response()  (BaseDetector helper, you call it)

shutdown
  -> cleanup()     -->  Release model resources
```

## Key Patterns

- **Never load models in `__init__()`** — use `initialize()` instead
- **Use `self._build_response()`** to return results (don't construct DetectionResponse manually)
- **Let exceptions propagate** from `detect()` — the framework catches them
- **Release video captures in `finally` blocks** to avoid resource leaks
- **Use `self.config`** to access user-provided config values
- **Internal port is always 5000** — the external port is set in manifest.json
