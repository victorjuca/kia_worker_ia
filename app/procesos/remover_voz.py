"""
Remover voz con audio-separator como libreria: cada modelo se carga UNA vez en la GPU y se reutiliza.

Igual que SegundaVoz.java: separa en kia_temp, normaliza el volumen del instrumental y al proyecto solo pasan las
pistas finales. De la voz separada siempre se guarda su onda en texto (rv_vocals.onda, la "Voz guia" del Karaoke
Studio); los vocals solo se conservan si el proceso lo pidio (info_extra "vocals=1"). Sin pedirlos, antes se
transcriben (callback 'antes_de_borrar_vocals').
"""
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .. import gpu, rutas
from ..proyecto import onda

log = logging.getLogger("remover_voz")


def nombres_salida(formato: str) -> dict[str, str]:
    """El formato de la tabla modelo: {"Vocals": "rv_vocals", "Instrumental": "rv_instrumental"} (con o sin comillas)."""
    f = (formato or "").strip().strip("'")
    try:
        d = json.loads(f)
        if isinstance(d, dict):
            return {str(k): str(v) for k, v in d.items()}
    except ValueError:
        pass
    return {k.strip(): v.strip() for k, v in re.findall(r'["\']?([\w\- ]+?)["\']?\s*:\s*["\']?([\w\-]+)["\']?\s*(?:,|}|$)', f)}


def nombre_instrumental(nombres: dict[str, str]) -> str | None:
    for k, v in nombres.items():
        if k.strip().lower() == "instrumental":
            return v
    for v in nombres.values():
        if "instrumental" in v.lower():
            return v
    return None


class RemoverVoz:
    def __init__(self, cfg):
        self.cfg = cfg
        self._separadores = {}
        self.antes_de_cargar: Callable[[], None] | None = None   # libera Whisper (lo conecta main.py)

    def libera(self, excepto: str | None = None):
        """Saca de la GPU los modelos cargados (menos 'excepto')."""
        quitar = [m for m in self._separadores if m != excepto]
        for m in quitar:
            del self._separadores[m]
            log.info("Modelo %s liberado de la GPU", m)
        if quitar:
            gpu.vacia()

    def _separador(self, modelo: str, salida: Path):
        if self.cfg.liberar_gpu:
            self.libera(excepto=modelo)
            if self.antes_de_cargar is not None:
                self.antes_de_cargar()
        sep = self._separadores.get(modelo)
        if sep is None:
            from audio_separator.separator import Separator  # tarda: se importa al primer uso

            log.info("Cargando modelo %s ...", modelo)
            opciones = {}
            if self.cfg.separador_autocast:
                opciones["use_autocast"] = True          # media precision en la GPU: mas rapido
            if self.cfg.separador_overlap:
                opciones["mdxc_params"] = {"segment_size": 256, "override_model_segment_size": False,
                                           "batch_size": None, "overlap": self.cfg.separador_overlap, "pitch_shift": 0}
            sep = Separator(output_dir=str(salida), output_format="MP3",
                            model_file_dir=str(self.cfg.modelos_dir / "audio-separator"), **opciones)
            sep.load_model(model_filename=modelo)
            self._separadores[modelo] = sep
            log.info("Modelo %s listo", modelo)
        else:
            sep.output_dir = str(salida)
            instancia = getattr(sep, "model_instance", None)
            if instancia is not None:
                instancia.output_dir = str(salida)
        return sep

    def _guarda_onda(self, vocals: Path, carpeta: Path):
        """Voz guia del Karaoke Studio en texto (rv_vocals.onda): siempre la de rv_vocals.mp3; la de rv_sv_vocals.mp3
        solo si aun no hay. Si falla no detiene el proceso."""
        destino = carpeta / onda.ARCHIVO
        if vocals.name.lower() != rutas.VOCALS and destino.is_file():
            return
        try:
            tmp = vocals.with_name(onda.ARCHIVO)          # se arma en kia_temp y despues se coloca en el proyecto
            onda.genera(vocals, tmp, self.cfg.ffmpeg)
            rutas.coloca(tmp, destino)
            log.info("Onda de la voz: %s", destino.name)
        except Exception:
            log.warning("No se pudo guardar la onda de la voz", exc_info=True)

    def _normaliza(self, instrumental: Path):
        """loudnorm + volumen, igual que SegundaVoz.modificarVolumen."""
        if not instrumental.is_file():
            raise FileNotFoundError(f"No se generó el instrumental: {instrumental.name}")
        tmp = instrumental.with_name(instrumental.stem + "_tmp.mp3")
        r = subprocess.run([self.cfg.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(instrumental),
                            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,volume=1.3", str(tmp)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ffmpeg no pudo ajustar el volumen: " + r.stderr[-300:])
        tmp.replace(instrumental)

    def ejecutar(self, mp3: Path, modelos, conservar_vocals: bool,
                 antes_de_borrar_vocals: Callable[[Path], None] | None = None) -> int:
        """Separa con cada modelo activo. Regresa cuantos modelos terminaron bien (error si ninguno)."""
        if not mp3.is_file():
            raise FileNotFoundError(f"No existe la canción: {mp3}")
        if not modelos:
            raise RuntimeError("No hay modelos activos para remover voz (parámetros modelo_rv / modelo_rv_sv).")
        carpeta = mp3.parent
        ok, errores = 0, []
        for m in modelos:
            tmp = rutas.temp_nueva(self.cfg.kia_temp, "rv")
            try:
                nombres = nombres_salida(m.formato)
                log.info("Separando con %s -> %s", m.nombre, nombres)
                self._separador(m.nombre, tmp).separate(str(mp3), custom_output_names=nombres)
                instr = nombre_instrumental(nombres)
                if instr:
                    self._normaliza(tmp / f"{instr}.mp3")
                for f in sorted(tmp.iterdir()):
                    if not f.is_file():
                        continue
                    if rutas.es_vocals(f.name):
                        self._guarda_onda(f, carpeta)
                    if not conservar_vocals and rutas.es_vocals(f.name):
                        if antes_de_borrar_vocals is not None:
                            antes_de_borrar_vocals(f)
                        continue
                    rutas.coloca(f, carpeta / f.name)
                ok += 1
            except Exception as e:
                log.exception("El modelo %s falló", m.nombre)
                errores.append(f"{m.nombre}: {e}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if ok == 0:
            raise RuntimeError("Ningún modelo pudo completar el proceso. " + " | ".join(errores))
        return ok
