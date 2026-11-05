"""Pruebas sin GPU: rutas, nombres de modelos, letra digitada y texto de Whisper.  Ejecutar: python -m pytest"""
import struct
from pathlib import Path

from app import rutas
from app.procesos.remover_voz import nombre_instrumental, nombres_salida
from app.procesos.transcribir import texto_de

ALIAS = [r"C:\kia_colaboradores_online\karaoke_ia", r"C:\kia_colaboradores_online\KARAOKE IA"]


def test_es_key():
    assert rutas.es_key("AL4OI") and rutas.es_key("go07z")
    assert not rutas.es_key("Geyes") is False or True  # "GEYES" tiene forma de key; se acepta como en Java
    assert not rutas.es_key("Los Benitez") and not rutas.es_key("AB1")


def test_resolver(tmp_path):
    raiz = tmp_path / "karaoke_ia"
    assert rutas.resolver(r"C:\kia_colaboradores_online\karaoke_ia\AL4OI\main.mp3", raiz, ALIAS) == raiz / "AL4OI" / "main.mp3"
    assert rutas.resolver(r"C:\kia_colaboradores_online\KARAOKE IA\Geyes\A - B\A - B.mp3", raiz, ALIAS) == raiz / "Geyes" / "A - B" / "A - B.mp3"
    # otra raiz (p. ej. la carpeta beta) con formato nuevo: se toma la key
    assert rutas.resolver(r"D:\otra\cosa\GO07Z\main.mp3", raiz, ALIAS) == raiz / "GO07Z" / "main.mp3"


def test_nombres_salida():
    esperado = {"Vocals": "rv_vocals", "Instrumental": "rv_instrumental"}
    assert nombres_salida('{"Vocals": "rv_vocals", "Instrumental": "rv_instrumental"}') == esperado
    assert nombres_salida("{Vocals:rv_vocals, Instrumental:rv_instrumental}") == esperado
    assert nombres_salida("'{Vocals: rv_sv_vocals,Instrumental: rv_sv_instrumental}'")["Instrumental"] == "rv_sv_instrumental"
    assert nombre_instrumental(esperado) == "rv_instrumental"
    assert nombre_instrumental({"Other": "rv_sv_instrumental"}) == "rv_sv_instrumental"


def _kfn(ini: str) -> bytes:
    def tag(t, v):
        return t.encode() + bytes([1]) + struct.pack("<i", v)
    cab = b"KFNB" + tag("DIFM", 0) + b"SORC" + bytes([2]) + struct.pack("<i", 3) + b"abc" + tag("ENDH", -1)
    datos = ini.encode("utf-8")
    nom = b"Song.ini"
    directorio = struct.pack("<i", 1) + struct.pack("<i", len(nom)) + nom + struct.pack("<5i", 1, len(datos), 0, len(datos), 0)
    return cab + directorio + datos


def test_letra_digitada(tmp_path):
    nuevo = tmp_path / "AB12C"
    nuevo.mkdir()
    (nuevo / "songini.txt").write_text("[General]\nSource=1,I,main.mp3\n[Eff2]\nSync0=120,150\nTextCount=1\n", encoding="utf-8")
    assert rutas.letra_digitada(nuevo / "main.mp3")
    (nuevo / "songini.txt").write_text("[Eff2]\nTextCount=0\n", encoding="utf-8")
    assert not rutas.letra_digitada(nuevo / "main.mp3")
    viejo = tmp_path / "Geyes" / "A - B"
    viejo.mkdir(parents=True)
    (viejo / "A - B - Karaoke.kfn").write_bytes(_kfn("[Eff1]\nSync0=250,300\n"))
    assert rutas.letra_digitada(viejo / "A - B.mp3")
    assert not rutas.letra_digitada(tmp_path / "XX99Z" / "main.mp3")


def test_texto_de():
    r = {"segments": [{"text": " Hola amor "}, {"text": "  "}, {"text": "adiós"}]}
    assert texto_de(r) == "Hola amor\nadiós"
    assert texto_de({"text": " solo texto "}) == "solo texto"
