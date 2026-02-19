FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TF_CPP_MIN_LOG_LEVEL=2

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG DEVICE=cpu

RUN if [ "$DEVICE" = "gpu" ]; then \
        pip install --no-cache-dir 'tensorflow[and-cuda]>=2.15.0,<2.18.0'; \
    elif [ "$(dpkg --print-architecture)" = "arm64" ]; then \
        pip install --no-cache-dir 'tensorflow>=2.15.0,<2.18.0'; \
    else \
        pip install --no-cache-dir 'tensorflow-cpu>=2.15.0,<2.18.0'; \
    fi

COPY detectors/boboskyy_fall_detect/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY detectors/boboskyy_fall_detect/models/best_model.keras /app/models/best_model.keras

COPY core/ /app/core/
COPY detectors/boboskyy_fall_detect/detector.py /app/detector.py
COPY detectors/boboskyy_fall_detect/app.py /app/app.py

ENV PYTHONPATH="/app"
EXPOSE 5000
CMD ["python", "app.py"]
