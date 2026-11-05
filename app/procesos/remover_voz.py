"""
Remover voz con audio-separator como libreria: cada modelo se carga UNA vez en la GPU y se reutiliza.

Igual que SegundaVoz.java: separa en kia_temp, normaliza el volumen del instrumental y al proyecto solo pasan las
pistas finales. Los vocals solo se conservan si el proceso lo pidio (info_extra "vocals=1"); si no, antes de
borrarlos se transcriben (callback 'antes_de_borrar_vocals').
"""
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .. import rutas

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

    def _separador(self, modelo: str, salida: Path):
        sep = self._separadores.get(modelo)
        if sep is None:
            from audio_separator.separator import Separator  # tarda: se importa al primer uso

            log.info("Cargando modelo %s ...", modelo)
            sep = Separator(output_dir=str(salida), output_format="MP3",
                            model_file_dir=str(self.cfg.modelos_dir / "audio-separator"))
            sep.load_model(model_filename=modelo)
            self._separadores[modelo] = sep
            log.info("Modelo %s listo", modelo)
        else:
            sep.output_dir = str(salida)
            instancia = getattr(sep, "model_instance", None)
            if instancia is not None:
                instancia.output_dir = str(salida)
        return sep

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
