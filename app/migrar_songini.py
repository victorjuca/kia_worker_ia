"""
Sube a la base (tabla songini, version_2.1.sql de kia) el Song.ini de los proyectos que todavia lo tienen en
archivo (songini.txt o main.kfn), para que ya no dependan de el.

    python -m app.migrar_songini              sube los que falten (no borra nada)
    python -m app.migrar_songini --borrar     ademas borra songini.txt cuando la base ya tiene el mismo texto

Solo sube si la base no tiene Song.ini de esa cancion o si tiene la copia vieja (version 0). Si en la base ya hay
una version guardada por kia (version 1 o mas), esa manda y el archivo no se sube.
"""
import argparse
import logging
import sys

from . import rutas
from .config import Config
from .fila import Fila

log = logging.getLogger("migrar_songini")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--borrar", action="store_true", help="borra songini.txt si la base ya tiene el mismo texto")
    args = ap.parse_args()
    logging.basicConfig(level="INFO", stream=sys.stdout, format="%(levelname)-7s %(message)s")
    cfg = Config()
    fila = Fila(cfg)
    subidos = iguales = en_base = sin_archivo = errores = borrados = 0
    for carpeta in sorted(p for p in cfg.path_main.iterdir() if p.is_dir() and rutas.es_key(p.name)):
        key = carpeta.name.upper()
        texto = rutas.song_ini_archivo(carpeta / rutas.MP3)
        if texto is None:
            sin_archivo += 1
            continue
        try:
            actual = fila.songini(key)
            if actual is not None and actual[1] > 0:
                if actual[0].strip() == texto.strip():
                    iguales += 1
                else:
                    en_base += 1          # la base ya tiene una version guardada por kia: esa manda
            else:
                estado, desc = fila.guardar_songini(key, texto)
                if estado != "0":
                    raise RuntimeError(desc)
                subidos += 1
                log.info("%s subido", key)
                actual = (texto, 1)
            archivo = carpeta / rutas.SONGINI
            if args.borrar and archivo.is_file() and actual[0].strip() == texto.strip():
                archivo.unlink()
                borrados += 1
        except Exception as e:
            errores += 1
            log.error("%s: %s", key, e)
    log.info("Subidos: %d | ya iguales: %d | la base tiene otra version (no se tocó): %d | sin archivo: %d | "
             "errores: %d | songini.txt borrados: %d", subidos, iguales, en_base, sin_archivo, errores, borrados)


if __name__ == "__main__":
    main()
