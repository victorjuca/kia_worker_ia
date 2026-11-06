import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.procesos.descargar import es_youtube, video_id
from app.proyecto import portada, receta, songini


def test_songini_vacio():
    t = songini.texto("Los Invasores De Nuevo León", "Aguanta Corazón")
    assert t.startswith("[General]\nTitle=Aguanta Corazón\nArtist=Los Invasores De Nuevo León\n")
    assert "Source=1,I,main.mp3\n" in t
    assert "LibImage=Fondo Karaoke IA_sin_logo.jpg\n" in t
    assert "Mark8\n" in t and "TextCount=0\nInSync=1\n" in t


def test_renglones_de_la_caratula():
    assert portada.arma_renglones("Amor") == ["Amor"]
    assert portada.arma_renglones("Quiero Que Sepas") == ["Quiero", "Que", "Sepas"]
    assert portada.arma_renglones("El Rey De Los Caminos") == ["El Rey", "De Los", "Caminos"]


def test_video_id():
    assert video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1") == "dQw4w9WgXcQ"
    assert video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert es_youtube("https://youtu.be/x") and not es_youtube("C:/musica/a.mp3")


def _clip(n):
    return [receta.Clip(np.arange(n * 2, dtype=np.float32).reshape(n, 2), 0)]


def test_receta_pasos_basicos():
    assert [(c.start, len(c.pcm)) for c in receta._recorte(_clip(10), 2, 5)] == [(0, 7)]
    assert [(c.start, len(c.pcm)) for c in receta._hueco(_clip(10), 2, 5)] == [(0, 2), (5, 5)]
    assert [(c.start, len(c.pcm)) for c in receta._dividir(_clip(10), [3, 7])] == [(0, 3), (3, 4), (7, 3)]
    assert receta._fade(_clip(10), 0, 5, True)[0].pcm[:5, 0].tolist() == [0.0, 0.5, 2.0, 4.5, 8.0]
    assert receta.limpia("#kia-receta-audio v1 sr=44100\nRECORTAR 0 10\n\n") == ["RECORTAR 0 10"]


@pytest.mark.skipif(subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0, reason="sin ffmpeg")
def test_circulo(tmp_path: Path):
    src = tmp_path / "m.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x480", "-frames:v", "1", str(src)], check=True)
    portada.crea_circulo(src, tmp_path / "c.png")
    from PIL import Image
    im = Image.open(tmp_path / "c.png")
    assert im.size == (400, 400) and im.getpixel((0, 0))[3] == 0 and im.getpixel((200, 200))[3] == 255
