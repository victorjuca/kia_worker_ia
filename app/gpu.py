"""
Memoria de la GPU. Con tarjetas de 8 GB no caben a la vez Whisper y los modelos de remover voz: en Windows,
cuando se llena, el driver usa la RAM del sistema y todo se vuelve decenas de veces mas lento.
Con LIBERAR_GPU=true (por omision) solo queda cargado en la GPU el modelo que se esta usando.
"""
import gc
import logging

log = logging.getLogger("gpu")


def vacia():
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            libre, total = torch.cuda.mem_get_info()
            log.debug("GPU libre: %.1f de %.1f GB", libre / 2**30, total / 2**30)
    except Exception:  # sin torch o sin CUDA no hay nada que vaciar
        pass
