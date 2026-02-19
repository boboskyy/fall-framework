FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 ffmpeg curl gcc g++ \
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

RUN pip install --no-cache-dir \
    setuptools wheel cython numpy pillow pysparkling \
    python-json-logger importlib_metadata

RUN pip install --no-cache-dir --no-build-isolation --no-deps openpifpaf==0.13.6

COPY detectors/taufeeque_human_fall/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN python -c "import openpifpaf; openpifpaf.network.Factory(checkpoint='shufflenetv2k16').factory()"

COPY core/ /app/core/
COPY detectors/taufeeque_human_fall/repo/ /app/repo/
COPY detectors/taufeeque_human_fall/detector.py /app/detector.py
COPY detectors/taufeeque_human_fall/app.py /app/app.py

ENV PYTHONPATH="/app:/app/repo"
ENV MPLBACKEND=Agg
EXPOSE 5000
CMD ["python", "app.py"]
