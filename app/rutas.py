"""
Rutas y nombres fijos de los proyectos de kia (formato KARAOKE IA/<KEY>/main.mp3), igual que ProyectoCancion.java.

Las rutas de bitacora_proceso se guardaron en Windows (C:\\kia_colaboradores_online\\karaoke_ia\\KEY\\main.mp3);
resolver() las traduce a la carpeta de proyectos de este equipo o contenedor (PATH_MAIN).
"""
import os
import re
import shutil
import struct
import uuid
from pathlib import Path, PureWindowsPath

MP3 = "main.mp3"
SONGINI = "songini.txt"
KFN_ANTERIOR = "main.kfn"
VOCALS = "rv_vocals.mp3"
VOCALS_SV = "rv_sv_vocals.mp3"
INSTRUMENTAL = "rv_instrumental.mp3"
INSTRUMENTAL_SV = "rv_sv_instrumental.mp3"
WHISPER_JSON = "rv_vocals.json"
CIRCULO = "circulo.png"
PORTADA = "portada.jpg"

_KEY = re.compile(r"^[A-Z0-9]{5,8}$")


def es_key(nombre: str) -> bool:
    return bool(nombre) and bool(_KEY.match(nombre.strip().upper()))


def resolver(path_bitacora: str, path_main: Path, alias: list[str]) -> Path:
    """Ruta de la bitacora -> ruta en este equipo. Si ya existe tal cual, se usa asi."""
    if not path_bitacora:
        raise ValueError("El proceso no trae ruta")
    if Path(path_bitacora).exists():
        return Path(path_bitacora)
    pw = PureWindowsPath(path_bitacora)
    texto = str(pw)
    for raiz in alias:
        r = str(PureWindowsPath(raiz)).rstrip("\\")
        if texto.lower().startswith(r.lower() + "\\"):
            relativo = PureWindowsPath(texto[len(r) + 1:])
            return path_main.joinpath(*relativo.parts)
    # formato nuevo con otra raiz: .../<KEY>/archivo
    if es_key(pw.parent.name):
        return path_main / pw.parent.name.upper() / pw.name
    return Path(path_bitacora)


def es_vocals(nombre: str) -> bool:
    """rv_vocals.mp3 / rv_sv_vocals.mp3 (voz separada), no los instrumentales."""
    n = nombre.lower()
    return n.endswith(".mp3") and "vocals" in n and "instrumental" not in n


def temp_nueva(kia_temp: Path, prefijo: str) -> Path:
    d = kia_temp / f"{prefijo}-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def coloca(origen: Path, destino: Path) -> None:
    """Mueve un archivo terminado (desde kia_temp) a su lugar, reemplazando el anterior."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(origen, destino)          # misma unidad: instantaneo
    except OSError:
        tmp = destino.with_name(destino.name + ".kia-tmp")
        shutil.copy2(origen, tmp)            # otra unidad: copia y despues reemplaza
        os.replace(tmp, destino)
        origen.unlink(missing_ok=True)


# ------------------------------------------------------------------ letra digitada (songini / .kfn)

def archivo_karaoke(mp3: Path) -> Path:
    """songini.txt (formato nuevo) o "Artista - Cancion - Karaoke.kfn" (formato viejo) del proyecto de ese mp3."""
    if mp3.name.lower() == MP3:
        si = mp3.parent / SONGINI
        return si if si.exists() or not (mp3.parent / KFN_ANTERIOR).exists() else mp3.parent / KFN_ANTERIOR
    return mp3.parent / (mp3.stem + " - Karaoke.kfn")


def song_ini_de_kfn(datos: bytes) -> str:
    """Texto del Song.ini dentro de un .kfn (mismo formato que Kfn.java)."""
    if datos[:4] != b"KFNB":
        raise ValueError("No es un .kfn")
    i = 4
    while True:
        tag = datos[i:i + 4].decode("latin-1")
        tipo = datos[i + 4]
        i += 5
        if tipo == 1:
            i += 4
        elif tipo == 2:
            (n,) = struct.unpack_from("<i", datos, i)
            i += 4 + n
        else:
            raise ValueError(f"Campo desconocido {tag}")
        if tag == "ENDH":
            break
    (n,) = struct.unpack_from("<i", datos, i)
    i += 4
    entradas = []
    for _ in range(n):
        (ln,) = struct.unpack_from("<i", datos, i)
        nombre = datos[i + 4:i + 4 + ln].decode("utf-8", "replace")
        i += 4 + ln
        _tipo, _olen, off, elen, _enc = struct.unpack_from("<5i", datos, i)
        i += 20
        entradas.append((nombre, off, elen))
    for nombre, off, elen in entradas:
        if nombre.lower() == "song.ini":
            return datos[i + off:i + off + elen].decode("utf-8", "replace")
    raise ValueError("El .kfn no trae Song.ini")


def resumen(ini: str) -> tuple[int, int]:
    """(Sync0 en centesimas o -1, total de marcas de tiempo): lo que se guarda junto al Song.ini en la base
    (ProyectoSongIni.resumen de kia)."""
    inicio, marcas = -1, 0
    for linea in (ini or "").splitlines():
        t = linea.strip()
        if not t.startswith("Sync") or "=" not in t:
            continue
        valores = t.split("=", 1)[1].split(",")
        marcas += sum(1 for v in valores if v.strip())
        if t.startswith("Sync0="):
            try:
                inicio = int(valores[0].strip())
            except ValueError:
                inicio = -1
    return inicio, marcas


def song_ini_archivo(mp3: Path) -> str | None:
    """Song.ini del songini.txt / .kfn del proyecto si todavia existe el archivo (proyectos sin migrar)."""
    k = archivo_karaoke(mp3)
    if not k.is_file():
        return None
    try:
        if k.suffix.lower() == ".txt":
            return k.read_text(encoding="utf-8-sig", errors="replace")
        return song_ini_de_kfn(k.read_bytes())
    except Exception:
        return None


def letra_digitada(mp3: Path, ini: str | None = None) -> bool:
    """True si el proyecto ya tiene la letra digitada (primera marca Sync0 mayor que 0), como KFNDumper.
    'ini' es el Song.ini de la base; sin el, se busca el archivo del proyecto."""
    texto = ini if ini is not None else song_ini_archivo(mp3)
    return bool(texto) and resumen(texto)[0] > 0
