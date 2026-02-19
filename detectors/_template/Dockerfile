FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Device selection: cpu (default) or gpu
ARG DEVICE=cpu

# Install PyTorch — CPU-only wheels (~200MB) or full CUDA (~2.5GB)
# Remove/replace if using TensorFlow instead
RUN if [ "$DEVICE" = "gpu" ]; then \
        pip install --no-cache-dir torch torchvision; \
    elif [ "$(dpkg --print-architecture)" = "arm64" ]; then \
        pip install --no-cache-dir torch torchvision; \
    else \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
    fi

# Install detector-specific requirements
COPY detectors/{{DETECTOR_NAME}}/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy framework core (shared across all detectors)
COPY core/ /app/core/

# Copy the original repo code (model weights, inference scripts, etc.)
COPY detectors/{{DETECTOR_NAME}}/repo/ /app/repo/

# Copy adapter code
COPY detectors/{{DETECTOR_NAME}}/detector.py /app/detector.py
COPY detectors/{{DETECTOR_NAME}}/app.py /app/app.py

# Set Python path so imports work
ENV PYTHONPATH="/app"

EXPOSE 5000

CMD ["python", "app.py"]
