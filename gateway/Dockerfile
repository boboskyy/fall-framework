
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY core/ /app/core/

COPY gateway/ /app/gateway/

RUN pip install --no-cache-dir \
    flask==3.0.* \
    flask-cors>=4.0.0 \
    werkzeug==3.0.* \
    requests>=2.31.0 \
    docker>=7.0.0

EXPOSE 5000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/v1/health || exit 1

CMD ["python", "-m", "gateway.app"]
