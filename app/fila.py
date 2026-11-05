"""
Fila de procesos (bitacora_proceso) con las mismas funciones de la base que usa la barredora de kia:
sps_procesadora, valida_entrega_procesos, iniciar_proceso_v2, spu_termino_proceso y spu_error_proceso.
"""
import base64
import logging
from dataclasses import dataclass

import psycopg

log = logging.getLogger("fila")

TIPO_REMOVER_VOZ = 1
TIPO_TRANSCRIBIR = 5
ID_MODELO_RV_SV = 1
ID_MODELO_RV = 2
INFO_CONSERVAR_VOCALS = "vocals=1"


@dataclass
class Proceso:
    id: int
    path: str
    tipo: int
    cancion_id: int | None


@dataclass
class Modelo:
    id: int
    nombre: str
    formato: str


class Fila:
    def __init__(self, cfg):
        self.cfg = cfg
        self._cn = None

    # ------------------------------------------------------------------ conexion
    def _conexion(self):
        if self._cn is None or self._cn.closed:
            self._cn = psycopg.connect(
                host=self.cfg.db_host, port=self.cfg.db_port, dbname=self.cfg.db_nombre,
                user=self.cfg.db_usuario, password=self.cfg.db_password,
                autocommit=True, connect_timeout=15, application_name="kia-worker-ia")
        return self._cn

    def _ejecuta(self, sql, params=(), todos=False):
        try:
            with self._conexion().cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if todos else cur.fetchone()
        except psycopg.OperationalError:
            self._cn = None          # se reconecta en la siguiente vuelta
            raise

    def cierra(self):
        if self._cn is not None and not self._cn.closed:
            self._cn.close()

    # ------------------------------------------------------------------ fila
    def es_procesadora(self) -> tuple[bool, str]:
        r = self._ejecuta("select * from sps_procesadora(%s)", (self.cfg.maquina_id,))
        arr = r[0] if r else None
        return bool(arr) and arr[0] == "0", (arr[1] if arr and len(arr) > 1 else "sin respuesta")

    def pendientes(self, tipos: tuple[int, ...]) -> list[Proceso]:
        filas = self._ejecuta(
            "select id, path, id_tipo_proceso, cancion_id from valida_entrega_procesos(%s)",
            (self.cfg.maquina_id,), todos=True)
        return [Proceso(f[0], f[1], f[2], f[3]) for f in filas if f[2] in tipos]

    def iniciar(self, id_proceso: int) -> tuple[bool, str]:
        """Asigna el proceso a esta maquina (estado 2 En Proceso) respetando los limites de maquina_proceso."""
        r = self._ejecuta("select * from iniciar_proceso_v2(%s, %s)", (self.cfg.maquina_id, id_proceso))
        arr = r[0] if r else None
        ok = bool(arr) and arr[0] == "0" and len(arr) > 3 and str(arr[3]).lower() == "true"
        return ok, (arr[1] if arr and len(arr) > 1 else "sin respuesta")

    def terminar(self, path_bitacora: str, tipo: int):
        self._ejecuta("select * from spu_termino_proceso(%s, %s)", (path_bitacora, tipo))

    def error(self, id_proceso: int, mensaje: str):
        # bitacora_error.error es varchar(255)
        m = mensaje if len(mensaje) <= 255 else mensaje[:120] + "..." + mensaje[-130:]
        self._ejecuta("select * from spu_error_proceso(%s, %s)", (id_proceso, m))

    def info_extra(self, id_proceso: int) -> str:
        r = self._ejecuta("select info_extra from bitacora_proceso where id = %s", (id_proceso,))
        return (r[0] or "") if r else ""

    # ------------------------------------------------------------------ datos
    def parametro_activo(self, nombre: str) -> bool:
        r = self._ejecuta("select valor from sps_parametro(%s)", (nombre,))
        return bool(r) and str(r[0]).strip().lower() == "true"

    def modelos_activos(self) -> list[Modelo]:
        """Los modelos de remover voz encendidos con los parametros modelo_rv_sv (id 1) y modelo_rv (id 2)."""
        activos = {ID_MODELO_RV_SV: self.parametro_activo("modelo_rv_sv"), ID_MODELO_RV: self.parametro_activo("modelo_rv")}
        filas = self._ejecuta("select id, nombre, formato from sps_modelo()", todos=True)
        return [Modelo(f[0], f[1], f[2]) for f in filas if activos.get(f[0])]

    def guardar_letra_transcrita(self, cancion_id: int, texto: str):
        """Letra "Transcrita IA" (tipo 1), igual que el proceso Transcribir de kia."""
        enc = base64.b64encode(texto.encode("utf-8")).decode("ascii")
        r = self._ejecuta("select * from spu_letra_cancion(%s, %s, %s)", (cancion_id, enc, 1))
        arr = r[0] if r else None
        if not arr or arr[0] != "0":
            log.warning("No se guardó la letra transcrita de la canción %s: %s", cancion_id, arr[1] if arr else "sin respuesta")
