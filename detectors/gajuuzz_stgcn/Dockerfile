FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG DEVICE=cpu

RUN if [ "$DEVICE" = "gpu" ]; then \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu128 --extra-index-url https://pypi.org/simple; \
    elif [ "$(dpkg --print-architecture)" = "arm64" ]; then \
        pip install --no-cache-dir torch torchvision; \
    else \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
    fi

COPY detectors/gajuuzz_stgcn/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY core/ /app/core/

# Upstream repo (GajuuzZ/Human-Falling-Detect-Tracks) + Models/ weights.
# Must be populated BEFORE build — see README_INTEGRACJA.md.
COPY detectors/gajuuzz_stgcn/repo/ /app/repo/

COPY detectors/gajuuzz_stgcn/detector.py /app/detector.py
COPY detectors/gajuuzz_stgcn/app.py /app/app.py

# repo/ must be importable (DetectorLoader, PoseEstimateLoader, Track, ActionsEstLoader)
ENV PYTHONPATH="/app:/app/repo"

EXPOSE 5000

CMD ["python", "app.py"]
