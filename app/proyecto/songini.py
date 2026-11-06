"""
songini.txt sin digitar (KaraokeFUNForm.defineGeneral de kia): datos de la cancion, fondo de la app y una pista de
letra vacia. Karaoke Studio lo abre igual que el Song.ini de un .kfn.
"""
import datetime
import uuid
from pathlib import Path

from .. import rutas

FONDO_SIN_LOGO = "Fondo Karaoke IA_sin_logo.jpg"

_CON = "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿĀāĂăĄąĆćĈĉĊċČčĎďĐđĒēĔĕĖėĘęĚěĜĝĞğĠġȑȒȓȔȕȗȘș"
_SIN = "AAAAAAACEEEEIIIIDNOOOOOOUUUUYBaaaaaaaceeeeiiiionoooooouuuuybyAaAaAaCcCcCcCcDdDdEeEeEeEeEeGgGgGgrRrUuuSs"
_TABLA = str.maketrans(_CON, _SIN)


def remover_acentos(s: str) -> str:
    return s.translate(_TABLA)


def texto(artista: str, nombre: str, mp3: str = rutas.MP3, fondo: str = FONDO_SIN_LOGO, letra: str | None = None) -> str:
    l = ["[General]", f"Title={nombre}", f"Artist={artista}", "Album=", "Composer=",
         f"Year={datetime.date.today().year}", "Track=", "GenreID=-1", "Copyright=", "Comment=",
         f"Source=1,I,{remover_acentos(mp3)}", "EffectCount=2", "LanguageID=", "DiffMen=0", "DiffWomen=0",
         "KFNType=0", "Properties=24", "KaraokeVersion=", "VocalGuide=", "KaraFunization=", "InfoScreenBmp=",
         "GlobalShift=0", "", "[Marks]"]
    l += [f"Mark{i}" for i in range(9)]
    l += ["", "[MP3Music]", "NumTracks=0", "",
          "[Eff1]", "ID=51", "InPractice=0", "Enabled=-1", "Locked=0", "Color=#000000",
          f"LibImage={remover_acentos(fondo)}", "ImageColor=#FFFFFFFF", "AlphaBlending=Opacity", "OffsetX=0",
          "OffsetY=0", "Depth=0", "NbAnim=0", "",
          "[Eff2]", "ID=2", "InPractice=1", "Enabled=-1", "Locked=0", "Font=Arial Black*50",
          "ActiveColor=#FF0000FF", "InactiveColor=#FFFFFFFF", "FrameColor=#000000FF", "InactiveFrameColor=#000000FF",
          "FrameType=Frame2", "FrameType=1", "Preview=1", "Fixed=0", "LineCount=4", "OffsetX=0", "OffsetY=0",
          "NbAnim=0"]
    renglones = [] if not letra or not letra.strip() else (letra + "\n-").split("\n")
    l.append(f"TextCount={len(renglones)}")
    l += [f"Text{i}={t}" for i, t in enumerate(renglones)]
    l.append("InSync=1")
    return "".join(x + "\n" for x in l)


def crea(carpeta: Path, artista: str, nombre: str, kia_temp: Path) -> Path:
    """Escribe songini.txt (via kia_temp, fuera de Drive)."""
    destino = carpeta / rutas.SONGINI
    kia_temp.mkdir(parents=True, exist_ok=True)
    tmp = kia_temp / f"songini-{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_bytes(texto(artista, nombre).encode("utf-8"))
        rutas.coloca(tmp, destino)
    finally:
        tmp.unlink(missing_ok=True)
    return destino
