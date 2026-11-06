"""Whisper como libreria: el modelo se carga UNA vez y se reutiliza en cada cancion."""
import json
import logging
import uuid
from pathlib import Path

from typing import Callable

from .. import gpu, rutas

log = logging.getLogger("whisper")


def texto_de(resultado: dict) -> str:
    """Un renglon por segmento, igual que TranscribirService.textoDesdeJson."""
    segs = resultado.get("segments") or []
    if segs:
        return "\n".join(s["text"].strip() for s in segs if s.get("text", "").strip())
    return (resultado.get("text") or "").strip()


class Transcriptor:
    def __init__(self, cfg):
        self.cfg = cfg
        self._modelo = None
        self.antes_de_cargar: Callable[[], None] | None = None   # libera los modelos de remover voz (main.py)

    def libera(self):
        if self._modelo is not None:
            self._modelo = None
            log.info("Whisper liberado de la GPU")
            gpu.vacia()

    def _carga(self):
        if self.cfg.liberar_gpu and self.antes_de_cargar is not None:
            self.antes_de_cargar()
        if self._modelo is None:
            import whisper  # se importa aqui: tarda y necesita torch

            log.info("Cargando Whisper %s en %s ...", self.cfg.whisper_modelo, self.cfg.whisper_device)
            self._modelo = whisper.load_model(self.cfg.whisper_modelo, device=self.cfg.whisper_device,
                                              download_root=str(self.cfg.modelos_dir / "whisper"))
            log.info("Whisper listo")
        return self._modelo

    def transcribir(self, audio: Path, json_destino: Path) -> str:
        """Transcribe 'audio' (la voz separada) y deja el JSON de Whisper (con tiempos por palabra) en json_destino."""
        modelo = self._carga()
        resultado = modelo.transcribe(str(audio), language=self.cfg.whisper_idioma, word_timestamps=True,
                                      fp16=self.cfg.whisper_device == "cuda", verbose=False)
        self.cfg.kia_temp.mkdir(parents=True, exist_ok=True)
        tmp = self.cfg.kia_temp / f"whisper-{uuid.uuid4().hex[:8]}.json"
        try:
            tmp.write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")
            rutas.coloca(tmp, json_destino)
        finally:
            tmp.unlink(missing_ok=True)
        return texto_de(resultado)
