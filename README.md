# kia-worker-ia

Worker de IA de **kia**: toma de la fila de procesos (`bitacora_proceso`) los procesos de
**Remover voz (1)** y **Transcribir (5)** y los ejecuta **uno a la vez**, con los modelos cargados una sola
vez en la GPU (audio-separator y Whisper como librerías de Python, no por consola).

Hace lo mismo que la barredora de kia:

- Usa las mismas funciones de la base: `sps_procesadora`, `valida_entrega_procesos`, `iniciar_proceso_v2`,
  `spu_termino_proceso`, `spu_error_proceso`. La app de escritorio ve el avance igual que hoy.
- **Remover voz:** separa en `kia_temp`, normaliza el volumen del instrumental y al proyecto solo pasan las pistas
  finales. Los vocals solo se guardan si el proceso trae `vocals=1` (casilla *Vocals* de la pantalla Remover voz);
  si no, antes de borrarlos se transcriben con Whisper (si `transcribir_whisper` está activo y la letra aún no
  está digitada) y al proyecto solo llega `rv_vocals.json`.
- **Transcribir (manual):** siempre transcribe `rv_vocals.mp3`.
- En los dos casos la letra se guarda en la base como *Transcrita IA*.
- Las rutas de la fila (`C:\kia_colaboradores_online\...`) se traducen a `PATH_MAIN` de este equipo o contenedor.

> Mientras se prueba, **detén la barredora de kia** en ese equipo para que no tomen los mismos procesos.

## En Windows (sin Docker)

```powershell
cd C:\Users\turing\Documents\claude\kia-worker-ia
conda activate kia-worker

# 1. torch con CUDA (una vez). cu121 sirve para drivers NVIDIA recientes.
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# 2. dependencias
pip install -r requirements.txt

# 3. configuracion
copy .env.example .env      # y llena los datos de la base

# 4. pruebas sin GPU
python -m pytest

# 5. arrancar (Ctrl+C para detener)
python -m app.main
```

La primera vez descarga los modelos en `modelos\` (audio-separator y Whisper); después ya no.

## Con Docker (GPU NVIDIA)

Requiere Docker Desktop con WSL2 y soporte de GPU.

```powershell
docker build -t kia-worker-ia .
docker run --gpus all --env-file .env -e WORKER_MAQUINA_ID=<id-de-la-maquina-del-worker> `
  -v "C:\kia_colaboradores_online\karaoke_ia:/data/karaoke_ia" `
  -v "C:\kia_main\kia_temp:/data/kia_temp" `
  -v "${PWD}\modelos:/modelos" kia-worker-ia
```

En Docker, `WORKER_MAQUINA_ID` es obligatorio: da de alta una máquina para el worker (pantalla *Máquinas* de
kia) con *procesador* activo y los procesos *Remover Voz* y *Transcribir* habilitados.

## Estructura

```
app/
  main.py          ciclo: revisa la fila cada INTERVALO_SEG y ejecuta un proceso a la vez
  config.py        configuración desde .env / variables de entorno
  fila.py          funciones de la base (fila, parámetros, modelos, letra)
  rutas.py         nombres fijos, rutas de la fila -> este equipo, letra digitada
  procesos/
    remover_voz.py audio-separator (modelos cargados una vez)
    transcribir.py Whisper (modelo cargado una vez)
tests/             pruebas sin GPU (python -m pytest)
```
"# kia_worker_ia" 
