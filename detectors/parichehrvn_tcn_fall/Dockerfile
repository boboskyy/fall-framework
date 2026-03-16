FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG DEVICE=cpu

RUN if [ "$DEVICE" = "gpu" ]; then \
        pip install --no-cache-dir torch torchvision; \
    elif [ "$(dpkg --print-architecture)" = "arm64" ]; then \
        pip install --no-cache-dir torch torchvision; \
    else \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
    fi

COPY detectors/parichehrvn_tcn_fall/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY core/ /app/core/

COPY detectors/parichehrvn_tcn_fall/repo/ /app/repo/

COPY detectors/parichehrvn_tcn_fall/detector.py /app/detector.py
COPY detectors/parichehrvn_tcn_fall/app.py /app/app.py

ENV PYTHONPATH="/app:/app/repo"
ENV YOLO_AUTOINSTALL=false
ENV YOLO_VERBOSE=false

EXPOSE 5000

CMD ["python", "app.py"]
