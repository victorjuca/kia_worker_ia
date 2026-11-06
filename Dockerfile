# Worker de IA de kia (Remover voz + Whisper) con GPU NVIDIA.
#   docker build -t kia-worker-ia .
#   docker run --gpus all --env-file .env -e WORKER_MAQUINA_ID=... ^
#     -v "C:\kia_colaboradores_online\karaoke_ia:/data/karaoke_ia" ^
#     -v "C:\kia_main\kia_temp:/data/kia_temp" -v "%cd%\modelos:/modelos" kia-worker-ia
FROM python:3.11-slim

# Indice de torch con CUDA (las ruedas traen CUDA/cuDNN; el contenedor solo necesita el driver del equipo: --gpus all)
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    DEBIAN_FRONTEND=noninteractive \
    PATH_MAIN=/data/karaoke_ia \
    KIA_TEMP=/data/kia_temp \
    MODELOS_DIR=/modelos \
    YTDLP_JS_RUNTIME=deno \
    FUENTE_PORTADA=/usr/share/fonts/truetype/kia/ariblk.ttf

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /worker
COPY requirements.txt .
# 1) dependencias (pasos separados: si uno falla se ve cual, y lo ya instalado queda en cache)
#    pip puede traer torch SIN CUDA como dependencia de audio-separator / whisper
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
# 2) despues se fuerza torch CON CUDA, para que nada lo vuelva a cambiar por la version de CPU
#    (al construir no hay GPU: torch.cuda.get_arch_list() da [] y se revisan las arquitecturas con que se compilo)
RUN pip uninstall -y torch torchvision torchaudio \
    && pip install --no-cache-dir torch torchvision torchaudio --index-url ${TORCH_INDEX} \
    && python -c "import torch; v = torch.__version__; a = torch._C._cuda_getArchFlags() or ''; print('torch', v, a); assert '+cu' in v, 'torch sin CUDA: ' + v; assert 'sm_120' in a, 'este torch no trae soporte para RTX 50xx (sm_120): usa cu128 o mas nuevo'"
# 3) JavaScript para yt-dlp (YouTube lo pide para descargar)
RUN pip install --no-cache-dir deno

COPY app ./app
COPY recursos ./recursos

# fuentes: monta la carpeta con ariblk.ttf (Arial Black) en /usr/share/fonts/truetype/kia
VOLUME ["/data/karaoke_ia", "/data/kia_temp", "/modelos"]
CMD ["python", "-m", "app.main"]
