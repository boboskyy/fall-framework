FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG DEVICE=cpu

RUN if [ "$DEVICE" = "gpu" ]; then \
        pip install --no-cache-dir 'tensorflow[and-cuda]>=2.10.0,<2.16.0'; \
    elif [ "$(dpkg --print-architecture)" = "arm64" ]; then \
        pip install --no-cache-dir 'tensorflow>=2.10.0,<2.16.0'; \
    else \
        pip install --no-cache-dir 'tensorflow-cpu>=2.10.0,<2.16.0'; \
    fi

COPY detectors/dzungvpham_twostream_cnn/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY core/ /app/core/

COPY detectors/dzungvpham_twostream_cnn/repo/ /app/repo/

COPY detectors/dzungvpham_twostream_cnn/detector.py /app/detector.py
COPY detectors/dzungvpham_twostream_cnn/app.py /app/app.py

RUN python -c "from tensorflow.keras.applications import MobileNetV2; MobileNetV2(weights='imagenet', include_top=False, input_shape=(224,224,3))"

ENV TF_CPP_MIN_LOG_LEVEL=2

EXPOSE 5000

CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]
