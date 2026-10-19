# PyInstaller-Spezifikation: baut dist\OCRDMS\OCRDMS.exe (ohne Konsolenfenster).
# Aufruf: .venv\Scripts\pyinstaller packaging\ocrdms.spec --noconfirm

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src" / "ocrdms"

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("ocrdms")
    + ["win32timezone", "win32serviceutil", "servicemanager", "pystray._win32", "multipart"]
)

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(SRC / "resources"), "ocrdms/resources")],
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "PySide6", "PyQt5", "PyQt6", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OCRDMS",
    icon=str(SRC / "resources" / "app.ico"),
    console=False,
    version=str(ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="OCRDMS")
