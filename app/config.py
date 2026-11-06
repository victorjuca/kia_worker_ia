"""Configuracion del worker: todo sale de variables de entorno (o del archivo .env de la carpeta del worker)."""
import os
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # sin python-dotenv se usan solo las variables del sistema
    pass


def _lista(valor: str) -> list[str]:
    return [v.strip() for v in (valor or "").split(";") if v.strip()]


def _id_maquina_windows() -> str:
    """El mismo identificador que usa kia (getMaquinaId de OSHI = UUID de Win32_ComputerSystemProduct)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
            capture_output=True, text=True, timeout=20,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _fuente_por_defecto() -> str:
    """Arial Black: la de Windows o, en Docker, la que se monte en /usr/share/fonts/truetype/kia."""
    if platform.system() == "Windows":
        return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "ariblk.ttf")
    return "/usr/share/fonts/truetype/kia/ariblk.ttf"


@dataclass
class Config:
    # base de datos (la misma de kia)
    db_host: str = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    db_port: int = field(default_factory=lambda: int(os.getenv("DB_PORT", "5432")))
    db_nombre: str = field(default_factory=lambda: os.getenv("DB_NAME", "kia"))
    db_usuario: str = field(default_factory=lambda: os.getenv("DB_USER", ""))
    db_password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", ""))

    # identificador de la maquina en la tabla maquina (columna mac). Vacio en Windows: el mismo que kia.
    maquina_id: str = field(default_factory=lambda: os.getenv("WORKER_MAQUINA_ID", ""))

    # carpeta de proyectos (PATH_MAIN de kia) en ESTE equipo / contenedor
    path_main: Path = field(default_factory=lambda: Path(os.getenv("PATH_MAIN", r"C:\kia_colaboradores_online\karaoke_ia")))
    # raices con las que se pudieron guardar las rutas en bitacora_proceso (separadas por ';')
    path_main_alias: list[str] = field(default_factory=lambda: _lista(os.getenv(
        "PATH_MAIN_ALIAS",
        r"C:\kia_colaboradores_online\karaoke_ia;C:\kia_colaboradores_online\KARAOKE IA;"
        r"C:\kia_colaboradores_online_beta\karaoke_ia;C:\kia_colaboradores_online_beta\KARAOKE IA")))

    # temporales (fuera de Drive) y modelos descargados
    kia_temp: Path = field(default_factory=lambda: Path(os.getenv("KIA_TEMP", r"C:\kia_main\kia_temp")))
    modelos_dir: Path = field(default_factory=lambda: Path(os.getenv("MODELOS_DIR", str(Path(__file__).resolve().parent.parent / "modelos"))))

    # whisper
    whisper_modelo: str = field(default_factory=lambda: os.getenv("WHISPER_MODELO", "large-v3-turbo"))
    whisper_idioma: str = field(default_factory=lambda: os.getenv("WHISPER_IDIOMA", "es"))
    whisper_device: str = field(default_factory=lambda: os.getenv("WHISPER_DEVICE", "cuda"))
    # audio-separator: autocast (media precision, mas rapido) y overlap de los modelos roformer (vacio = el del modelo)
    separador_autocast: bool = field(default_factory=lambda: os.getenv("SEPARADOR_AUTOCAST", "false").strip().lower() in ("1", "true", "si", "sí"))
    separador_overlap: int | None = field(default_factory=lambda: int(os.getenv("SEPARADOR_OVERLAP")) if os.getenv("SEPARADOR_OVERLAP", "").strip() else None)
    # true: solo un modelo a la vez en la GPU (tarjetas de 8 GB); false: los deja cargados (GPU de 16 GB o mas)
    liberar_gpu: bool = field(default_factory=lambda: os.getenv("LIBERAR_GPU", "true").strip().lower() in ("1", "true", "si", "sí"))

    ffmpeg: str = field(default_factory=lambda: os.getenv("FFMPEG", "ffmpeg"))

    # Descargar Cancion (yt-dlp) y caratula
    recursos_dir: Path = field(default_factory=lambda: Path(os.getenv("RECURSOS_DIR", str(Path(__file__).resolve().parent.parent / "recursos"))))
    fuente_portada: Path = field(default_factory=lambda: Path(os.getenv("FUENTE_PORTADA", _fuente_por_defecto())))
    portada_auto: bool = field(default_factory=lambda: os.getenv("PORTADA_AUTO", "true").strip().lower() in ("1", "true", "si", "sí"))
    ytdlp_js_runtime: str = field(default_factory=lambda: os.getenv("YTDLP_JS_RUNTIME", "node"))
    ytdlp_cookies: str = field(default_factory=lambda: os.getenv("YTDLP_COOKIES", ""))
    ytdlp_actualizar: bool = field(default_factory=lambda: os.getenv("YTDLP_ACTUALIZAR", "true").strip().lower() in ("1", "true", "si", "sí"))
    intervalo_seg: int = field(default_factory=lambda: int(os.getenv("INTERVALO_SEG", "10")))
    # que procesos toma este contenedor: 10 Descargar, 1 Remover voz, 5 Transcribir (separados por coma)
    tipos: tuple[int, ...] = field(default_factory=lambda: tuple(
        int(t) for t in os.getenv("WORKER_TIPOS", "1,5,10").replace(" ", "").split(",") if t))
    # candado en la base: un solo proceso a la vez en esta maquina entre el worker IA y kia-render
    un_proceso_por_maquina: bool = field(default_factory=lambda: os.getenv("UN_PROCESO_POR_MAQUINA", "true").strip().lower() in ("1", "true", "si", "sí"))

    def __post_init__(self):
        if not self.maquina_id and platform.system() == "Windows":
            self.maquina_id = _id_maquina_windows()

    def valida(self) -> list[str]:
        faltan = []
        if not self.db_usuario:
            faltan.append("DB_USER")
        if not self.maquina_id:
            faltan.append("WORKER_MAQUINA_ID")
        if not self.path_main.is_dir():
            faltan.append(f"PATH_MAIN ({self.path_main} no existe)")
        return faltan
