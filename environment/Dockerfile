# syntax=docker/dockerfile:1
# Entorno reproducible para la cápsula Code Ocean — BRENT Pattern System v2.
# Base CPU portable (Code Ocean puede sustituir esta línea por su imagen de
# registro al importar; el resto del recipe es válido en ambos casos).
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Dependencias del sistema mínimas (libgomp para PyTorch CPU).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU primero (rueda específica para evitar la build CUDA pesada).
RUN pip install --no-cache-dir \
        torch==2.2.2 torchvision==0.17.2 \
        --index-url https://download.pytorch.org/whl/cpu

# Resto de dependencias.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Reproducibilidad numérica determinista.
ENV PYTHONHASHSEED=0 \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4

WORKDIR /code
