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

    ffmpeg: str = field(default_factory=lambda: os.getenv("FFMPEG", "ffmpeg"))
    intervalo_seg: int = field(default_factory=lambda: int(os.getenv("INTERVALO_SEG", "10")))

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
