"""
Fila de procesos (bitacora_proceso) con las mismas funciones de la base que usa la barredora de kia:
sps_procesadora, valida_entrega_procesos, iniciar_proceso_v2, spu_termino_proceso y spu_error_proceso.
"""
import base64
import logging
import platform
import socket
from dataclasses import dataclass

import psycopg

log = logging.getLogger("fila")

TIPO_REMOVER_VOZ = 1
TIPO_TRANSCRIBIR = 5
TIPO_DESCARGAR = 10
ESTADO_AGREGADO, ESTADO_EN_PROCESO = 1, 2
ACCION_DESCARGA = 1          # acciones_sistema: la misma que registra kia al descargar
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
class Cancion:
    id: int
    key: str
    artista: str
    nombre: str


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
    def registrar_si_nueva(self) -> bool:
        """Si esta maquina (maquina_id) no existe en la tabla maquina, la inserta automaticamente.
        Devuelve True si la registro ahora, False si ya existia."""
        r = self._ejecuta(
            "SELECT id FROM maquina WHERE mac = %s",
            (self.cfg.maquina_id,)
        )
        if r:
            return False  # ya estaba registrada
        nombre_pc = socket.gethostname()
        nombre_usuario = os.environ.get("USER") or os.environ.get("USERNAME") or "worker"
        sistema = platform.system()   # 'Darwin', 'Linux', 'Windows'
        sobrenombre = f"{nombre_pc} ({sistema})"
        self._ejecuta(
            """INSERT INTO maquina (mac, nombre_pc, nombre_usuario, is_procesador, sobrenombre, usuario_id)
               VALUES (%s, %s, %s, true, %s, 1)""",
            (self.cfg.maquina_id, nombre_pc, nombre_usuario, sobrenombre)
        )
        return True

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

    # ------------------------------------------------------------------ un proceso a la vez por maquina
    def _clave_candado(self) -> str:
        return f"kia-proceso:{self.cfg.maquina_id}"

    def toma_candado(self) -> bool:
        """Candado de la base por maquina (el mismo que kia-render): mientras uno de los servicios de esta
        maquina tenga un proceso, el otro espera. Se suelta con suelta_candado o al cerrarse la conexion."""
        r = self._ejecuta("select pg_try_advisory_lock(hashtext(%s))", (self._clave_candado(),))
        return bool(r and r[0])

    def suelta_candado(self):
        try:
            self._ejecuta("select pg_advisory_unlock(hashtext(%s))", (self._clave_candado(),))
        except Exception:
            log.warning("No se pudo soltar el candado de la máquina (se suelta al cerrar la conexión)")

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

    # ------------------------------------------------------------------ descargar cancion
    def _cancion(self, where: str, valor) -> Cancion | None:
        r = self._ejecuta("select c.id, upper(trim(c.key)), a.nombre, c.nombre from cancion c "
                          "join artista a on a.id = c.artista_id where " + where, (valor,))
        return Cancion(r[0], r[1], (r[2] or "").strip(), (r[3] or "").strip()) if r else None

    def cancion(self, cancion_id: int) -> Cancion | None:
        return self._cancion("c.id = %s", cancion_id)

    def cancion_por_key(self, key: str) -> Cancion | None:
        return self._cancion("upper(trim(c.key)) = %s", key.strip().upper())

    def url_youtube(self, cancion_id: int) -> str | None:
        r = self._ejecuta("select url from url_cancion where cancion_id = %s and tipo_url_id = 1 order by id desc limit 1",
                          (cancion_id,))
        return r[0] if r else None

    def receta_audio(self, cancion_id: int) -> str | None:
        """Pasos del Editor de Audio (RecetaAudioRepository.obtener de kia), uno por renglon."""
        filas = self._ejecuta(
            "select o.clave, e.inicio, e.fin, e.valor from cancion_edit_audio e "
            "join edit_audio_operacion o on o.id = e.operacion_id where e.cancion_id = %s order by e.orden",
            (cancion_id,), todos=True)
        pasos = []
        for clave, inicio, fin, valor in filas:
            p = [clave]
            if inicio is not None:
                p.append(str(int(inicio)))
            if fin is not None:
                p.append(str(int(fin)))
            if valor is not None:
                v = format(valor.normalize(), "f") if hasattr(valor, "normalize") else str(valor)
                p.append(v)
            pasos.append(" ".join(p))
        return "\n".join(pasos) + "\n" if pasos else None

    def portada(self, cancion_id: int):
        """Coordenadas guardadas de la caratula (tabla portada) o None."""
        from .proyecto.portada import Parametros
        r = self._ejecuta(
            "select tamanoletraind, tamanofont, inicioy, saltolinea, anchocirculo, planoxcirculo, planoycirculo, "
            "nombreartistax, nombreartistay, nomartistatamfont from portada where cancion_id = %s order by id desc limit 1",
            (cancion_id,))
        return Parametros(*[int(v or 0) for v in r]) if r else None

    def pidio_remover_voz(self, cancion_id: int) -> bool:
        """Caracteristica 41 (remover_voz) de la cancion."""
        r = self._ejecuta("select sps_cancion_remover_voz(%s)", (cancion_id,))
        return bool(r and r[0])

    def encolar(self, tipo: int, path: str, cancion_id: int, key: str | None, info_extra: str | None = None) -> str:
        """FilaProcesoFrom.encolarSinConfirmar de kia: si ya esta Agregado / En proceso no hace nada; si existe en otro
        estado lo reinicia; si no existe lo inserta."""
        r = self._ejecuta("select sps_bitacora_proceso_estado_proceso(%s, %s)", (cancion_id, tipo))
        arr = r[0] if r else None
        existente = None
        if arr and arr[0] == "0" and len(arr) > 2 and arr[2]:
            partes = arr[2].strip("{}").split(",")
            existente = (int(partes[0]), int(partes[1]))
        if existente is None:
            r = self._ejecuta("select * from spi_asigna_proceso(%s, %s, %s, %s, %s)",
                              (tipo, path, cancion_id, key, info_extra or None))
            return (r[0][1] if r and r[0] else "sin respuesta")
        if existente[1] in (ESTADO_AGREGADO, ESTADO_EN_PROCESO):
            return "El proceso ya está en la fila."
        r = self._ejecuta("select * from spu_estado_bitacora(%s)", (existente[0],))
        if tipo == TIPO_REMOVER_VOZ:
            self._ejecuta("update bitacora_proceso set info_extra = %s where id = %s returning id",
                          (info_extra or None, existente[0]))
        return "Proceso reiniciado"

    def accion_sistema(self, accion: int, nombre: str):
        try:
            self._ejecuta("select * from spi_bitacora_acciones(%s, %s, %s, %s, %s)",
                          (self.cfg.maquina_id, accion, "kia-worker-ia", nombre, 0))
        except Exception:
            log.warning("No se pudo registrar la acción %s de %s", accion, nombre)

    # ------------------------------------------------------------------ Song.ini (version_2.1.sql de kia)
    def songini(self, key: str) -> tuple[str, int] | None:
        """(texto, version) del Song.ini de la cancion, o None si todavia no tiene."""
        r = self._ejecuta("select dato, version from sps_songini(%s)", (key,))
        return (r[0], r[1]) if r else None

    def guardar_songini(self, key: str, texto: str, version: int | None = None) -> tuple[str, str]:
        """spu_songini: estado '0' guardado, '1' error, '2' alguien guardo otra version."""
        from .rutas import resumen
        inicio, marcas = resumen(texto)
        r = self._ejecuta("select spu_songini(%s, %s, %s, %s, %s, %s, %s)",
                          (key, texto, version, inicio > 0, inicio if inicio >= 0 else None, marcas, "kia-worker-ia"))
        arr = r[0] if r else None
        return (arr[0], arr[1]) if arr else ("1", "sin respuesta")
