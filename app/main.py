"""
Worker de IA de kia: toma de la fila (bitacora_proceso) los procesos de Remover voz (1) y Transcribir (5)
y los ejecuta UNO A LA VEZ, con los modelos cargados una sola vez en la GPU.

Ejecutar:  python -m app.main
"""
import logging
import os
import signal
import sys
import time

from . import rutas
from .config import Config
from .fila import INFO_CONSERVAR_VOCALS, TIPO_REMOVER_VOZ, TIPO_TRANSCRIBIR, Fila, Proceso
from .procesos.remover_voz import RemoverVoz
from .procesos.transcribir import Transcriptor

log = logging.getLogger("worker")
TIPOS = (TIPO_REMOVER_VOZ, TIPO_TRANSCRIBIR)
NOMBRES = {TIPO_REMOVER_VOZ: "Remover voz", TIPO_TRANSCRIBIR: "Transcribir"}


class Worker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.fila = Fila(cfg)
        self.removedor = RemoverVoz(cfg)
        self.transcriptor = Transcriptor(cfg)
        self.en_curso: Proceso | None = None
        self.detener = False

    # ------------------------------------------------------------------ procesos
    def _transcribe_y_guarda(self, vocals, mp3, p: Proceso):
        """Whisper sobre la voz separada: rv_vocals.json al proyecto y la letra "Transcrita IA" a la base."""
        texto = self.transcriptor.transcribir(vocals, mp3.parent / rutas.WHISPER_JSON)
        if texto and p.cancion_id:
            self.fila.guardar_letra_transcrita(p.cancion_id, texto)
        log.info("Transcripción lista (%d renglones)", len(texto.splitlines()))

    def remover_voz(self, p: Proceso):
        mp3 = rutas.resolver(p.path, self.cfg.path_main, self.cfg.path_main_alias)
        conservar = INFO_CONSERVAR_VOCALS in self.fila.info_extra(p.id)
        whisper = self.fila.parametro_activo("transcribir_whisper") and not rutas.letra_digitada(mp3)

        def antes_de_borrar(vocals):
            # sin conservar los vocals: Whisper los usa (trabaja mejor con la voz aislada) y despues se borran
            if whisper and vocals.name.lower() == rutas.VOCALS:
                self._transcribe_y_guarda(vocals, mp3, p)

        self.removedor.ejecutar(mp3, self.fila.modelos_activos(), conservar, antes_de_borrar)
        if conservar and whisper and (mp3.parent / rutas.VOCALS).is_file():
            self._transcribe_y_guarda(mp3.parent / rutas.VOCALS, mp3, p)

    def transcribir(self, p: Proceso):
        # mandado a mano: se transcribe aunque la letra ya este digitada
        mp3 = rutas.resolver(p.path, self.cfg.path_main, self.cfg.path_main_alias)
        vocals = mp3.parent / rutas.VOCALS
        if not vocals.is_file():
            raise FileNotFoundError(f"No existe {rutas.VOCALS} (manda la canción a Remover voz con Vocals marcado)")
        self._transcribe_y_guarda(vocals, mp3, p)

    # ------------------------------------------------------------------ fila
    def una_vuelta(self) -> bool:
        """Toma y ejecuta un proceso. True si trabajo en algo."""
        procesadora, motivo = self.fila.es_procesadora()
        if not procesadora:
            log.debug("Esta máquina no procesa: %s", motivo)
            return False
        for p in self.fila.pendientes(TIPOS):
            ok, motivo = self.fila.iniciar(p.id)
            if not ok:
                log.debug("Proceso %s no asignado: %s", p.id, motivo)
                continue
            self.en_curso = p
            inicio = time.monotonic()
            log.info("== %s #%s: %s", NOMBRES[p.tipo], p.id, p.path)
            try:
                if p.tipo == TIPO_REMOVER_VOZ:
                    self.remover_voz(p)
                else:
                    self.transcribir(p)
                self.fila.terminar(p.path, p.tipo)
                log.info("== Terminado #%s en %.0f s", p.id, time.monotonic() - inicio)
            except Exception as e:
                log.exception("Error en el proceso #%s", p.id)
                self.fila.error(p.id, f"Error en {NOMBRES[p.tipo]} (worker IA): {e}")
            finally:
                self.en_curso = None
            return True   # un proceso a la vez
        return False

    def corre(self):
        log.info("Worker IA iniciado. Máquina: %s | Proyectos: %s | Temporales: %s",
                 self.cfg.maquina_id, self.cfg.path_main, self.cfg.kia_temp)
        while not self.detener:
            try:
                trabajo = self.una_vuelta()
            except Exception:
                log.exception("Error revisando la fila (se reintenta)")
                trabajo = False
            if not trabajo:
                for _ in range(self.cfg.intervalo_seg):
                    if self.detener:
                        break
                    time.sleep(1)
        self.fila.cierra()
        log.info("Worker detenido")

    def interrumpe(self, *_):
        """Ctrl+C / docker stop: si habia un proceso a medias se marca con error para poder reiniciarlo."""
        self.detener = True
        p = self.en_curso
        if p is not None:
            try:
                self.fila.error(p.id, "El worker IA se detuvo a la mitad del proceso; reinícialo.")
            except Exception:
                pass
            log.warning("Detenido a la mitad del proceso #%s", p.id)
            os._exit(1)


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), stream=sys.stdout,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    cfg = Config()
    faltan = cfg.valida()
    if faltan:
        log.error("Falta configurar: %s (revisa el archivo .env)", ", ".join(faltan))
        sys.exit(2)
    w = Worker(cfg)
    signal.signal(signal.SIGINT, w.interrumpe)
    signal.signal(signal.SIGTERM, w.interrumpe)
    w.corre()


if __name__ == "__main__":
    main()
