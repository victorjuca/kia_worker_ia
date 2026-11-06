"""
Receta de audio del Editor de Audio de kia (AudioEditor.aplicarReceta): los pasos guardados en
cancion_edit_audio se vuelven a aplicar sobre el main.mp3 recien descargado, antes de remover la voz.

Pasos (posiciones en frames a 44100 Hz):
  RECORTAR a b | HUECO a b | DIVIDIR a [b] | DEJAR_SOLO a b | GANANCIA a b dB | FADE_IN a b | FADE_OUT a b
  TONO semitonos | CUENTA | MOVER desde hasta
"""
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import rutas

SR = 44100


@dataclass
class Clip:
    pcm: np.ndarray      # (frames, 2) float32
    start: int

    @property
    def end(self) -> int:
        return self.start + len(self.pcm)

    def at(self, s: int) -> "Clip":
        return Clip(self.pcm, s)

    def part(self, desde: int, hasta: int) -> "Clip":
        return Clip(self.pcm[desde - self.start:hasta - self.start], desde)


def limpia(receta: str | None) -> list[str]:
    if not receta:
        return []
    return [l.strip() for l in receta.splitlines() if l.strip() and not l.strip().startswith("#")]


def tiene_receta(receta: str | None) -> bool:
    return bool(limpia(receta))


# ------------------------------------------------------------------ ffmpeg

def decodifica(ffmpeg: str, archivo: Path) -> np.ndarray:
    r = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(archivo), "-vn", "-f", "f32le", "-acodec", "pcm_f32le",
                        "-ac", "2", "-ar", str(SR), "pipe:1"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr.decode("utf-8", "replace")[-300:])
    return np.frombuffer(r.stdout, dtype="<f4").reshape(-1, 2).copy()


def _filtra(ffmpeg: str, pcm: np.ndarray, filtro: str) -> np.ndarray:
    r = subprocess.run([ffmpeg, "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
                        "-filter:a", filtro, "-f", "f32le", "-ar", str(SR), "-ac", "2", "pipe:1"],
                       input=pcm.astype("<f4").tobytes(), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr.decode("utf-8", "replace")[-300:])
    return np.frombuffer(r.stdout, dtype="<f4").reshape(-1, 2).copy()


def _codifica(ffmpeg: str, pcm: np.ndarray, destino: Path, etiquetas: Path):
    """mp3 320k conservando etiquetas y portada del original (AudioEditor.codificar)."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2",
                        "-i", "pipe:0", "-i", str(etiquetas), "-map", "0:a", "-map", "1:v?", "-map_metadata", "1",
                        "-c:a", "libmp3lame", "-b:a", "320k", "-c:v", "copy", "-id3v2_version", "3", "-f", "mp3",
                        str(destino)], input=pcm.astype("<f4").tobytes(), capture_output=True)
    if r.returncode != 0 or not destino.is_file() or destino.stat().st_size == 0:
        raise RuntimeError("ffmpeg: " + r.stderr.decode("utf-8", "replace")[-300:])


# ------------------------------------------------------------------ pasos

def _total(clips):
    return clips[-1].end if clips else 0


def _recorte(src, a, b):
    d, r = b - a, []
    for c in src:
        if c.end <= a:
            r.append(c)
        elif c.start >= b:
            r.append(c.at(c.start - d))
        else:
            pre_end, post_start = max(c.start, a), min(c.end, b)
            pcm = np.concatenate([c.pcm[:pre_end - c.start], c.pcm[post_start - c.start:]])
            if len(pcm):
                r.append(Clip(pcm, min(c.start, a)))
    return r


def _hueco(src, a, b):
    r = []
    for c in src:
        if c.end <= a or c.start >= b:
            r.append(c)
            continue
        if c.start < a:
            r.append(c.part(c.start, a))
        if c.end > b:
            r.append(c.part(b, c.end))
    return r


def _dividir(src, cortes):
    r = list(src)
    for p in cortes:
        t = []
        for c in r:
            if c.start < p < c.end:
                t += [c.part(c.start, p), c.part(p, c.end)]
            else:
                t.append(c)
        r = t
    return r


def _multiplica(src, a, b, g):
    r = []
    for c in src:
        s, e = max(a, c.start), min(b, c.end)
        if e <= s:
            r.append(c)
            continue
        pcm = c.pcm.copy()
        f = np.arange(s, e)
        pcm[s - c.start:e - c.start] *= g(f).astype(np.float32)[:, None]
        r.append(Clip(pcm, c.start))
    return r


def _fade(src, a, b, entrada):
    n = b - a

    def g(f):
        t = np.ones(len(f)) if n == 1 else (f - a) / float(n - 1)
        return t if entrada else 1 - t
    return _multiplica(src, a, b, g)


def _tono(ffmpeg, src, semitonos):
    ratio = 2 ** (semitonos / 12.0)
    filtro = f"asetrate={SR * ratio:.4f},aresample={SR},atempo={1 / ratio:.8f}"
    r = []
    for c in src:
        nuevo = _filtra(ffmpeg, c.pcm, filtro)[:len(c.pcm)]
        if len(nuevo) < len(c.pcm):
            nuevo = np.concatenate([nuevo, np.zeros((len(c.pcm) - len(nuevo), 2), np.float32)])
        r.append(Clip(nuevo, c.start))
    return r


def _mover(src, desde, hasta):
    r, movido = [], False
    for c in src:
        if not movido and c.start == desde:
            r.append(c.at(hasta))
            movido = True
        else:
            r.append(c)
    if not movido:
        raise RuntimeError(f"MOVER: no hay bloque que empiece en {desde}")
    return sorted(r, key=lambda c: c.start)


def _paso(clips, paso, ffmpeg, cuenta_mp3):
    t = paso.split()
    try:
        op, n = t[0], [float(x) for x in t[1:]]
        i = [int(x) for x in n] if op != "GANANCIA" else [int(n[0]), int(n[1])]
        if op == "RECORTAR":
            return _recorte(clips, i[0], i[1])
        if op == "HUECO":
            return _hueco(clips, i[0], i[1])
        if op == "DIVIDIR":
            return _dividir(clips, i)
        if op == "DEJAR_SOLO":
            return _recorte(_recorte(clips, i[1], max(i[1], _total(clips))), 0, i[0])
        if op == "GANANCIA":
            k = 10 ** (n[2] / 20.0)
            return _multiplica(clips, i[0], i[1], lambda f: np.full(len(f), k))
        if op == "FADE_IN":
            return _fade(clips, i[0], i[1], True)
        if op == "FADE_OUT":
            return _fade(clips, i[0], i[1], False)
        if op == "TONO":
            return _tono(ffmpeg, clips, n[0])
        if op == "CUENTA":
            pcm = decodifica(ffmpeg, cuenta_mp3)
            return [Clip(pcm, 0)] + [c.at(c.start + len(pcm)) for c in clips]
        if op == "MOVER":
            return _mover(clips, i[0], i[1])
    except (IndexError, ValueError) as e:
        raise RuntimeError(f"Paso mal formado en la receta: {paso}") from e
    raise RuntimeError(f"Paso desconocido en la receta: {paso}")


def aplica(mp3: Path, receta: str, ffmpeg: str, cuenta_mp3: Path, kia_temp: Path) -> bool:
    """Aplica la receta y sobrescribe el mp3. False si la receta esta vacia; error si un paso falla."""
    pasos = limpia(receta)
    if not pasos:
        return False
    clips = [Clip(decodifica(ffmpeg, mp3), 0)]
    for p in pasos:
        clips = sorted(_paso(clips, p, ffmpeg, cuenta_mp3), key=lambda c: c.start)
    total = _total(clips)
    if total <= 0:
        raise RuntimeError("La receta deja la canción sin audio.")
    r = np.zeros((total, 2), np.float32)
    for c in clips:
        r[c.start:c.end] = c.pcm      # como System.arraycopy: el bloque posterior pisa al anterior
    kia_temp.mkdir(parents=True, exist_ok=True)
    tmp = kia_temp / f"receta-{uuid.uuid4().hex[:8]}.mp3"
    try:
        _codifica(ffmpeg, r, tmp, mp3)
        rutas.coloca(tmp, mp3)
    finally:
        tmp.unlink(missing_ok=True)
    return True
