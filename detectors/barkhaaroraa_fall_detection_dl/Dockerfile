FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY detectors/barkhaaroraa_fall_detection_dl/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY core/ /app/core/

COPY detectors/barkhaaroraa_fall_detection_dl/detector.py /app/detector.py
COPY detectors/barkhaaroraa_fall_detection_dl/app.py /app/app.py

ENV PYTHONPATH="/app"
EXPOSE 5000
CMD ["python", "app.py"]
