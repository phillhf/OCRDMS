"""Pfade für Ressourcen und Anwendungsdaten – funktioniert im Quellcode, in der EXE und im Windows-Dienst.

Anwendungsdaten (Einstellungen, Zertifikate, Protokolle) liegen zentral unter %PROGRAMDATA%\\OCRDMS,
damit Dienst (läuft als SYSTEM) und manueller Start dieselben Daten verwenden.
Mit der Umgebungsvariable OCRDMS_DATA lässt sich der Ort überschreiben (z. B. für Tests).
"""

import os
import sys
from pathlib import Path

from . import APP_NAME


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ocrdms" / "resources"  # type: ignore[attr-defined]
    return Path(__file__).parent / "resources"


def tessdata_dir() -> Path:
    return resource_dir() / "tessdata"


def static_dir() -> Path:
    return resource_dir() / "web"


def app_data_dir() -> Path:
    override = os.environ.get("OCRDMS_DATA")
    if override:
        path = Path(override)
    else:
        base = os.environ.get("PROGRAMDATA") or os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def sub_dir(name: str) -> Path:
    path = app_data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    return sub_dir("logs")


def default_work_dir() -> Path:
    drive = os.environ.get("SystemDrive", "C:")
    return Path(drive + "\\") / APP_NAME
