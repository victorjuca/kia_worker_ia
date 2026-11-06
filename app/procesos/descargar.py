"""
Descargar Cancion (tipo 10), igual que la barredora de kia (DescargarCancionService + completaProyectoNuevo):

1. Baja el audio con yt-dlp en kia_temp (-x mp3, --audio-quality 2). Si falla: otros clientes de YouTube,
   actualizar yt-dlp una vez y, al final, pytubefix. Si la "URL" es un archivo de este equipo, se copia/convierte.
2. Aplica la receta del Editor de Audio (si la cancion tiene).
3. Pone main.mp3 en la carpeta del proyecto y le completa lo que le falte: songini.txt, circulo.png (miniatura de
   YouTube) y portada.jpg (coordenadas de la base o las de por defecto con ajuste automatico).
"""
import logging
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from .. import rutas
from ..fila import Cancion, Fila, Proceso
from ..proyecto import portada as caratula
from ..proyecto import receta, songini

log = logging.getLogger("descargar")

CLIENTES_RESPALDO = "youtube:player_client=default,tv,web_safari,android_vr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def es_youtube(url: str) -> bool:
    return bool(url) and ("youtube.com" in url or "youtu.be" in url)


def video_id(url: str) -> str | None:
    import re
    u = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", u):
        return u
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", u)
    return m.group(1) if m else None


class Descargador:
    def __init__(self, cfg, fila: Fila):
        self.cfg = cfg
        self.fila = fila
        self._ytdlp_actualizado = False
        self._fuente = None

    # ------------------------------------------------------------------ yt-dlp
    def _ytdlp(self, *args: str, timeout: int = 900) -> subprocess.CompletedProcess:
        cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-playlist"]
        runtime = (self.cfg.ytdlp_js_runtime or "").strip()
        if runtime and shutil.which(runtime):
            cmd += ["--js-runtimes", runtime]
        if self.cfg.ytdlp_cookies and Path(self.cfg.ytdlp_cookies).is_file():
            cmd += ["--cookies", str(self.cfg.ytdlp_cookies)]
        if self.cfg.ffmpeg and self.cfg.ffmpeg != "ffmpeg":
            cmd += ["--ffmpeg-location", self.cfg.ffmpeg]
        cmd += list(args)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if r.returncode != 0:
            log.info("yt-dlp: %s", (r.stderr or r.stdout).strip()[-400:])
        return r

    def _baja_audio(self, url: str, base: Path) -> Path | None:
        """base sin extension -> base.mp3 (yt-dlp -x --audio-format mp3 --audio-quality 2, como CMD_YT_DLP)."""
        mp3 = base.with_suffix(".mp3")
        args = ["-x", "--audio-format", "mp3", "--audio-quality", "2", "-o", str(base) + ".%(ext)s", url]
        self._ytdlp(*args)
        if mp3.is_file() or not es_youtube(url):
            return mp3 if mp3.is_file() else None
        log.info("[respaldo YouTube] reintentando con otros clientes")
        self._ytdlp(*args, "--extractor-args", CLIENTES_RESPALDO)
        if mp3.is_file():
            return mp3
        if not self._ytdlp_actualizado and self.cfg.ytdlp_actualizar:
            self._ytdlp_actualizado = True
            log.info("[respaldo YouTube] actualizando yt-dlp")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp[default]"],
                           capture_output=True, timeout=600)
            self._ytdlp(*args)
            if mp3.is_file():
                return mp3
        return mp3 if self._pytubefix(url, mp3) else None

    def _pytubefix(self, url: str, mp3: Path) -> bool:
        try:
            from pytubefix import YouTube
        except ImportError:
            return False
        try:
            log.info("[respaldo YouTube] pytubefix")
            stream = YouTube(url).streams.get_audio_only()
            origen = Path(stream.download(output_path=str(mp3.parent), filename="_pytubefix"))
            self._convierte(origen, mp3)
            origen.unlink(missing_ok=True)
            return mp3.is_file()
        except Exception as e:
            log.info("pytubefix: %s", e)
            return False

    def _convierte(self, origen: Path, mp3: Path):
        """CMD_FFMPEG_COVERTIR_MP3: ffmpeg -i origen -q:a 2 -map a mp3."""
        r = subprocess.run([self.cfg.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(origen),
                            "-q:a", "2", "-map", "a", str(mp3)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg no pudo convertir " + origen.name + ": " + r.stderr[-300:])

    def _miniatura(self, url: str, base: Path) -> Path | None:
        self._ytdlp("--ignore-errors", url, "--write-thumbnail", "--skip-download", "-o", str(base), timeout=120)
        for ext in (".jpg", ".png", ".webp"):
            if base.with_suffix(ext).is_file():
                return base.with_suffix(ext)
        vid = video_id(url) if es_youtube(url) else None
        for q in ("maxresdefault", "sddefault", "hqdefault") if vid else ():
            try:
                req = urllib.request.Request(f"https://i.ytimg.com/vi/{vid}/{q}.jpg", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=15) as r:
                    datos = r.read()
                if len(datos) > 3000:
                    destino = base.with_suffix(".jpg")
                    destino.write_bytes(datos)
                    return destino
            except Exception as e:
                log.info("miniatura %s: %s", q, e)
        return None

    # ------------------------------------------------------------------ proceso
    def ejecutar(self, p: Proceso) -> tuple[Path, Cancion]:
        mp3 = rutas.resolver(p.path, self.cfg.path_main, self.cfg.path_main_alias)
        carpeta = mp3.parent
        datos = (self.fila.cancion(p.cancion_id) if p.cancion_id else None) or \
            (self.fila.cancion_por_key(carpeta.name) if rutas.es_key(carpeta.name) else None)
        if datos is None:
            raise RuntimeError(f"No se encontró en la base la canción del proceso (cancion_id {p.cancion_id}, {carpeta.name})")
        url = (self.fila.info_extra(p.id) or "").strip() or (self.fila.url_youtube(datos.id) or "").strip()

        if not mp3.is_file():
            if not url:
                raise RuntimeError("La canción no tiene URL de YouTube")
            self._descarga(url, mp3, datos)
        self.completa(carpeta, datos, url)
        return mp3, datos

    def _descarga(self, url: str, mp3: Path, datos: Cancion):
        tmp = rutas.temp_nueva(self.cfg.kia_temp, "descarga")
        try:
            final = tmp / rutas.MP3
            local = Path(url)
            if local.is_file():
                # cancion registrada desde un archivo de este equipo: se copia (mp3) o se convierte
                if local.suffix.lower() == ".mp3":
                    shutil.copy2(local, final)
                else:
                    self._convierte(local, final)
            else:
                for intento in range(1, 3):
                    bajado = self._baja_audio(url, tmp / "main")
                    if bajado is not None and bajado.is_file() and bajado.stat().st_size > 0:
                        break
                    log.info("Descarga fallida (intento %d)", intento)
                else:
                    raise RuntimeError("No se pudo descargar la canción: " + url)
            if not final.is_file() or final.stat().st_size == 0:
                raise RuntimeError("La descarga quedó vacía")
            pasos = self.fila.receta_audio(datos.id)
            if receta.tiene_receta(pasos):
                try:
                    receta.aplica(final, pasos, self.cfg.ffmpeg, self.cfg.recursos_dir / "cuenta.mp3", self.cfg.kia_temp)
                    log.info("Receta de audio aplicada")
                except Exception:
                    log.exception("No se pudo aplicar la receta de audio; el mp3 queda como se descargó")
            rutas.coloca(final, mp3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _fuente_portada(self):
        if self._fuente is None:
            self._fuente = caratula.Fuente(self.cfg.fuente_portada)
        return self._fuente

    def completa(self, carpeta: Path, datos: Cancion, url: str):
        """completaProyectoNuevo: songini.txt, circulo.png y portada.jpg si faltan (lo demas no se toca)."""
        # el Song.ini vive en la base (version_2.1.sql de kia): se crea ahi si la cancion no lo tiene
        if self.fila.songini(datos.key) is None:
            texto = rutas.song_ini_archivo(carpeta / rutas.MP3)      # proyecto anterior con songini.txt / main.kfn
            estado, desc = self.fila.guardar_songini(datos.key, texto or songini.texto(datos.artista, datos.nombre))
            if estado != "0":
                raise RuntimeError("No se pudo guardar el Song.ini en la base: " + desc)
            log.info("Song.ini %s en la base", "subido" if texto else "creado")
        circulo = carpeta / rutas.CIRCULO
        if not circulo.is_file() and es_youtube(url):
            tmp = rutas.temp_nueva(self.cfg.kia_temp, "miniatura")
            try:
                img = self._miniatura(url, tmp / "_miniatura")
                if img is not None:
                    caratula.crea_circulo(img, tmp / rutas.CIRCULO)
                    rutas.coloca(tmp / rutas.CIRCULO, circulo)
                    log.info("circulo.png creado")
            except Exception:
                log.exception("No se pudo crear circulo.png")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        destino = carpeta / rutas.PORTADA
        if not destino.is_file():
            tmp = rutas.temp_nueva(self.cfg.kia_temp, "portada")
            try:
                fuente = self._fuente_portada()
                p = self.fila.portada(datos.id)
                if p is None or p.ancho_circulo <= 0:
                    p = caratula.define_parametros(fuente, datos.nombre, self.cfg.portada_auto)
                caratula.crea_portada(self.cfg.recursos_dir / "portada_youtube.png", fuente, datos.nombre, datos.artista,
                                      circulo if circulo.is_file() else None, p, tmp / rutas.PORTADA)
                rutas.coloca(tmp / rutas.PORTADA, destino)
                log.info("portada.jpg creada")
            except Exception:
                log.exception("No se pudo crear portada.jpg (se puede generar después desde kia)")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
