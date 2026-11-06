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
from .fila import ACCION_DESCARGA, INFO_CONSERVAR_VOCALS, TIPO_DESCARGAR, TIPO_REMOVER_VOZ, TIPO_TRANSCRIBIR, Fila, Proceso
from .procesos.descargar import Descargador
from .procesos.remover_voz import RemoverVoz
from .procesos.transcribir import Transcriptor

log = logging.getLogger("worker")
TIPOS = (TIPO_REMOVER_VOZ, TIPO_TRANSCRIBIR, TIPO_DESCARGAR)
NOMBRES = {TIPO_REMOVER_VOZ: "Remover voz", TIPO_TRANSCRIBIR: "Transcribir", TIPO_DESCARGAR: "Descargar canción"}


class Worker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.fila = Fila(cfg)
        self.removedor = RemoverVoz(cfg)
        self.transcriptor = Transcriptor(cfg)
        self.descargador = Descargador(cfg, self.fila)
        # en la GPU solo queda el modelo que se esta usando (LIBERAR_GPU)
        self.removedor.antes_de_cargar = self.transcriptor.libera
        self.transcriptor.antes_de_cargar = self.removedor.libera
        self.en_curso: Proceso | None = None
        self._ultimo_aviso = ""
        self.detener = False

    # ------------------------------------------------------------------ procesos
    def _transcribe_y_guarda(self, vocals, mp3, p: Proceso):
        """Whisper sobre la voz separada: rv_vocals.json al proyecto y la letra "Transcrita IA" a la base."""
        texto = self.transcriptor.transcribir(vocals, mp3.parent / rutas.WHISPER_JSON)
        if texto and p.cancion_id:
            self.fila.guardar_letra_transcrita(p.cancion_id, texto)
        log.info("Transcripción lista (%d renglones)", len(texto.splitlines()))

    def _letra_digitada(self, mp3) -> bool:
        """El Song.ini esta en la base; si la cancion todavia no lo tiene ahi, se revisa el archivo del proyecto."""
        ini = None
        if rutas.es_key(mp3.parent.name):
            try:
                r = self.fila.songini(mp3.parent.name.upper())
                ini = r[0] if r else None
            except Exception:
                log.warning("No se pudo leer el Song.ini de la base", exc_info=True)
        return rutas.letra_digitada(mp3, ini)

    def remover_voz(self, p: Proceso):
        mp3 = rutas.resolver(p.path, self.cfg.path_main, self.cfg.path_main_alias)
        conservar = INFO_CONSERVAR_VOCALS in self.fila.info_extra(p.id)
        whisper = self.fila.parametro_activo("transcribir_whisper") and not self._letra_digitada(mp3)

        def antes_de_borrar(vocals):
            # sin conservar los vocals: Whisper los usa (trabaja mejor con la voz aislada) y despues se borran (queda rv_vocals.onda)
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

    def descargar(self, p: Proceso):
        """Descarga y completa el proyecto; al terminar, si la cancion lo pidio, encola Remover voz (como kia)."""
        mp3, datos = self.descargador.ejecutar(p)
        self.fila.terminar(p.path, p.tipo)
        self.fila.accion_sistema(ACCION_DESCARGA, mp3.name)
        if self.fila.pidio_remover_voz(datos.id):
            r = self.fila.encolar(TIPO_REMOVER_VOZ, p.path, datos.id, datos.key, "")
            log.info("Remover voz encolado: %s", r)

    # ------------------------------------------------------------------ fila
    def una_vuelta(self) -> bool:
        """Toma y ejecuta un proceso. True si trabajo en algo."""
        procesadora, motivo = self.fila.es_procesadora()
        if not procesadora:
            self._avisa(f"Esta máquina no procesa: {motivo}")
            return False
        pendientes = self.fila.pendientes(self.cfg.tipos)
        if not pendientes:
            self._avisa("Sin procesos pendientes de " + " / ".join(NOMBRES.get(t, str(t)) for t in self.cfg.tipos))
            return False
        # un proceso a la vez entre todos los servicios de esta maquina (kia-render usa el mismo candado)
        candado = self.cfg.un_proceso_por_maquina
        if candado and not self.fila.toma_candado():
            self._avisa("Hay procesos pendientes, pero otro servicio de esta máquina tiene el candado "
                        "(un proceso a la vez); se espera")
            return False
        try:
            for p in pendientes:
                ok, motivo = self.fila.iniciar(p.id)
                if not ok:
                    self._avisa(f"Hay procesos pendientes pero no se asignan a esta máquina: {motivo}")
                    continue
                self.en_curso = p
                self._ultimo_aviso = ""
                inicio = time.monotonic()
                log.info("== %s #%s: %s", NOMBRES[p.tipo], p.id, p.path)
                try:
                    if p.tipo == TIPO_DESCARGAR:
                        self.descargar(p)          # termina el proceso antes de encolar Remover voz
                    else:
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
        finally:
            if candado:
                self.fila.suelta_candado()

    def _avisa(self, mensaje: str):
        """Dice una vez por que no se toman procesos (se repite solo si el motivo cambia)."""
        if mensaje != self._ultimo_aviso:
            log.warning(mensaje)
            self._ultimo_aviso = mensaje

    def corre(self):
        log.info("Worker iniciado (%s). Máquina: %s | Proyectos: %s | Temporales: %s",
                 ", ".join(NOMBRES.get(t, str(t)) for t in self.cfg.tipos),
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
