FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY requirements.zeabur.txt /app/requirements.zeabur.txt

RUN pip install --upgrade pip setuptools wheel && \
    pip install -r /app/requirements.txt && \
    pip install -r /app/requirements.zeabur.txt

COPY . /app

RUN chmod +x /app/entrypoint.sh && \
    mkdir -p /app/input /app/output /app/sam3_output /app/models

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
