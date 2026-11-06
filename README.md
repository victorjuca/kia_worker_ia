# kia-worker-ia

Worker de **kia**: toma de la fila de procesos (`bitacora_proceso`) los procesos de
**Descargar Canción (10)**, **Remover voz (1)** y **Transcribir (5)** y los ejecuta **uno a la vez**, con los modelos cargados una sola
vez en la GPU (audio-separator y Whisper como librerías de Python, no por consola).

Hace lo mismo que la barredora de kia:

- Usa las mismas funciones de la base: `sps_procesadora`, `valida_entrega_procesos`, `iniciar_proceso_v2`,
  `spu_termino_proceso`, `spu_error_proceso`. La app de escritorio ve el avance igual que hoy.
- **Remover voz:** separa en `kia_temp`, normaliza el volumen del instrumental y al proyecto solo pasan las pistas
  finales. Los vocals solo se guardan si el proceso trae `vocals=1` (casilla *Vocals* de la pantalla Remover voz);
  si no, antes de borrarlos se transcriben con Whisper (si `transcribir_whisper` está activo y la letra aún no
  está digitada) y al proyecto solo llega `rv_vocals.json`.
- **Descargar Canción:** baja el audio con yt-dlp en `kia_temp` (si falla: otros clientes de YouTube, actualizar
  yt-dlp una vez y pytubefix), le aplica la receta del Editor de Audio si la canción tiene, deja `main.mp3` en el
  proyecto y le completa lo que falte: `songini.txt`, `circulo.png` (miniatura de YouTube) y `portada.jpg` (con las
  coordenadas guardadas o las de por defecto con ajuste automático, igual que kia). Si la canción tiene la
  característica *remover_voz*, encola el Remover voz.
- **Transcribir (manual):** siempre transcribe `rv_vocals.mp3`.
- En los dos casos la letra se guarda en la base como *Transcrita IA*.
- Las rutas de la fila (`C:\kia_colaboradores_online\...`) se traducen a `PATH_MAIN` de este equipo o contenedor.

> Mientras se prueba, **detén la barredora de kia** en ese equipo para que no tomen los mismos procesos.
>
> **Un proceso a la vez por máquina:** el worker y `kia-render` usan el mismo candado en la base
> (`UN_PROCESO_POR_MAQUINA=true`, por omisión). Si los dos usan el mismo `WORKER_MAQUINA_ID`, mientras uno
> trabaja el otro espera.

## En Windows (sin Docker)

```powershell
cd C:\Users\turing\Documents\claude\kia-worker-ia
conda activate kia-worker

# 1. dependencias
pip install -r requirements.txt

# 2. torch CON CUDA, siempre DESPUES del paso 1: pip puede haber puesto torch de CPU como dependencia.
#    cu128 para tarjetas RTX 50xx / drivers recientes; cu126 si tu driver es mas viejo.
pip uninstall -y torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
#    debe decir algo como 2.x.x+cu128 True

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
docker build -t kia-worker-ia .          # instala torch con CUDA (cu126); otra: --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128
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
  gpu.py           libera la memoria de la GPU entre modelos
  procesos/
    descargar.py   yt-dlp + completar el proyecto (songini, circulo, portada, receta)
    remover_voz.py audio-separator
    transcribir.py Whisper
  proyecto/
    songini.py     songini.txt sin digitar (KaraokeFUNForm de kia)
    portada.py     circulo.png y portada.jpg (CancionForm de kia)
    receta.py      receta del Editor de Audio (AudioEditor de kia)
recursos/          portada_youtube.png (fondo de la portada) y cuenta.mp3
tests/             pruebas sin GPU (python -m pytest)
```
"# kia_worker_ia" 

## Descargar Canción

- Necesita **node** (o deno) para yt-dlp: el mismo node que ya usa kia (`YTDLP_JS_RUNTIME=node`). En Docker ya va deno.
- La portada se dibuja con **Arial Black** (`C:\Windows\Fonts\ariblk.ttf`). En Docker monta una carpeta con
  `ariblk.ttf` y `arial.ttf` en `/usr/share/fonts/truetype/kia`.
- Para que este worker descargue en lugar de la barredora de kia:

```sql
-- el worker descarga (tipo 10)
insert into maquina_proceso (maquina_id, tipo_proceso_id, procesa, numero_ejecuta)
select m.id, 10, true, 1 from maquina m where m.mac = 'RTX5060-WORKER-IA'
  and not exists (select 1 from maquina_proceso mp where mp.maquina_id = m.id and mp.tipo_proceso_id = 10);
-- la maquina de kia ya no descarga
update maquina_proceso set procesa = false where maquina_id = 20 and tipo_proceso_id = 10;
```

## Que procesos toma (WORKER_TIPOS)

Con la misma imagen de codigo se arman dos contenedores (ver `docker-compose.yml` de la carpeta de arriba):

| Contenedor | WORKER_TIPOS | Imagen | GPU |
|---|---|---|---|
| kia-descarga | `10` | `Dockerfile.descarga` (ligera, sin torch) | no |
| kia-worker-ia | `1,5` | `Dockerfile` | si |

Sin Docker, `WORKER_TIPOS` vacio = `1,5,10` (todo).

## Song.ini en la base

Desde `version_2.1.sql` de kia el Song.ini (letra y tiempos) vive en la tabla `songini`; los proyectos ya no
necesitan `songini.txt`. Para subir los que todavia estan en archivo:

```powershell
python -m app.migrar_songini            # sube los que falten (no borra nada)
python -m app.migrar_songini --borrar   # y borra songini.txt cuando la base ya tiene el mismo texto
```

En Docker: `docker compose run --rm kia-descarga python -m app.migrar_songini`.
