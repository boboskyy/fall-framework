FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    MPLBACKEND=Agg

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

COPY detectors/cwlroda_openpifpaf/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY detectors/cwlroda_openpifpaf/repo/ /app/openpifpaf/

RUN printf 'from .configparser import ConfigParser\n' > /app/openpifpaf/config/__init__.py

RUN cd /app/openpifpaf && \
    cc -shared -fPIC -O2 \
    -I$(python -c 'import numpy; print(numpy.get_include())') \
    -I$(python -c 'import sysconfig; print(sysconfig.get_path("include"))') \
    functional.c \
    -o functional$(python -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')

RUN python -c "\
import torch, os; \
d = os.path.join(torch.hub.get_dir(), 'checkpoints'); \
os.makedirs(d, exist_ok=True); \
url = 'http://github.com/vita-epfl/openpifpaf-torchhub/releases/download/v0.11.0/shufflenetv2k16w-200510-221334-cif-caf-caf25-o10s-604c5956.pkl'; \
torch.hub.download_url_to_file(url, os.path.join(d, os.path.basename(url))); \
print('Checkpoint downloaded')"

COPY core/ /app/core/
COPY detectors/cwlroda_openpifpaf/detector.py /app/detector.py
COPY detectors/cwlroda_openpifpaf/app.py /app/app.py

ENV PYTHONPATH="/app"
EXPOSE 5000
CMD ["python", "app.py"]
