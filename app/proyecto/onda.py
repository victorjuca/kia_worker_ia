"""
"Voz guia" del Karaoke Studio en texto (rv_vocals.onda): la onda de la voz separada reducida a min / max por bloques
de 512 muestras, igual que Studio.vocalPeaksOf / OndaVoz.java de kia. ~50 KB en vez de los 3-8 MB del rv_vocals.mp3.

    kia-onda 1
    bloque=512
    sr=44100
    n=20480
    datos=<base64: por bloque un byte min y un byte max, 0..255 = -1..1>
"""
import base64
import subprocess
from pathlib import Path

import numpy as np

ARCHIVO = "rv_vocals.onda"
CABECERA = "kia-onda 1"
BLOQUE = 512
SR = 44100


def picos(muestras: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """muestras estereo intercaladas (float32) -> (min, max) por bloque de la mezcla mono, el pico mas alto vale 1."""
    n = len(muestras) // 2 // BLOQUE
    mono = (muestras[: n * BLOQUE * 2:2] + muestras[1: n * BLOQUE * 2:2]) * 0.5
    bloques = mono.reshape(n, BLOQUE) if n else np.zeros((0, BLOQUE), np.float32)
    mn, mx = bloques.min(axis=1) if n else np.zeros(0), bloques.max(axis=1) if n else np.zeros(0)
    top = max(1e-6, float(-mn.min()) if n else 0.0, float(mx.max()) if n else 0.0)
    return mn / top, mx / top


def texto(mn: np.ndarray, mx: np.ndarray) -> str:
    q = lambda v: np.clip(np.round((v + 1.0) * 127.5), 0, 255).astype(np.uint8)
    b = np.empty(len(mn) * 2, np.uint8)
    b[0::2], b[1::2] = q(mn), q(mx)
    return (f"{CABECERA}\nbloque={BLOQUE}\nsr={SR}\nn={len(mn)}\n"
            f"datos={base64.b64encode(b.tobytes()).decode('ascii')}\n")


def genera(mp3: Path, destino: Path, ffmpeg: str = "ffmpeg") -> Path:
    """Decodifica el mp3 con ffmpeg (estereo, 44.1 kHz, float) y escribe la onda en texto."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(mp3),
                        "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg no pudo leer " + mp3.name + ": " + r.stderr.decode(errors="replace")[-300:])
    mn, mx = picos(np.frombuffer(r.stdout, dtype="<f4"))
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(texto(mn, mx), encoding="utf-8")
    tmp.replace(destino)
    return destino
