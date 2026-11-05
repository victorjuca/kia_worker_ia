# Worker de IA de kia (Remover voz + Whisper) con GPU NVIDIA.
#   docker build -t kia-worker-ia .
#   docker run --gpus all --env-file .env -e WORKER_MAQUINA_ID=... ^
#     -v "C:\kia_colaboradores_online\karaoke_ia:/data/karaoke_ia" ^
#     -v "C:\kia_main\kia_temp:/data/kia_temp" -v "%cd%\modelos:/modelos" kia-worker-ia
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    DEBIAN_FRONTEND=noninteractive \
    PATH_MAIN=/data/karaoke_ia \
    KIA_TEMP=/data/kia_temp \
    MODELOS_DIR=/modelos

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /worker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

VOLUME ["/data/karaoke_ia", "/data/kia_temp", "/modelos"]
CMD ["python", "-m", "app.main"]
