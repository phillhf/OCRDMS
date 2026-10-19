"""Updates über GitHub-Releases: neue Version erkennen, Installer laden, prüfen und still installieren.

Bei einem privaten Repository wird ein GitHub-Token mit Leserecht (Contents: read) benötigt.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from . import __version__
from .paths import sub_dir

log = logging.getLogger(__name__)

API = "https://api.github.com"
ASSET_RE = re.compile(r"^OCRDMS-Setup-[\d.]+\.exe$", re.IGNORECASE)
CHECK_INTERVAL_S = 12 * 3600


class UpdateError(RuntimeError):
    pass


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.lstrip("vV"))
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


@dataclass
class UpdateInfo:
    current: str = __version__
    latest: str = ""
    available: bool = False
    notes: str = ""
    published: str = ""
    asset_id: int = 0
    asset_name: str = ""
    size: int = 0
    digest: str = ""  # "sha256:…" (von GitHub für Release-Dateien bereitgestellt)
    checked_at: float = 0.0
    error: str = ""


class Updater:
    def __init__(self, get_config):
        """`get_config()` liefert (repo, token) – so wirken geänderte Einstellungen sofort."""
        self.get_config = get_config
        self.info = UpdateInfo()
        self.state = "idle"  # idle | checking | downloading | installing | error
        self.progress = 0
        self._lock = threading.Lock()

    def _headers(self, token: str, binary: bool = False) -> dict:
        h = {"Accept": "application/octet-stream" if binary else "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28", "User-Agent": f"OCRDMS/{__version__}"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    # ---------- Prüfen
    def check(self) -> UpdateInfo:
        repo, token = self.get_config()
        info = UpdateInfo(checked_at=time.time())
        if not repo:
            info.error = "Kein GitHub-Repository eingestellt"
            self.info = info
            return info
        try:
            r = requests.get(f"{API}/repos/{repo}/releases/latest", headers=self._headers(token), timeout=20)
        except requests.RequestException as e:
            info.error = f"GitHub nicht erreichbar: {e}"
        else:
            if r.status_code == 404:
                info.error = ("Kein Release gefunden. Bei einem privaten Repository wird ein GitHub-Token "
                              "mit Leserecht benötigt." if not token else "Kein Release gefunden oder Token ohne Zugriff.")
            elif r.status_code in (401, 403):
                info.error = f"GitHub verweigert den Zugriff ({r.status_code}) – Token prüfen."
            elif not r.ok:
                info.error = f"GitHub-Fehler {r.status_code}"
            else:
                rel = r.json()
                info.latest = rel.get("tag_name", "").lstrip("vV")
                info.notes = (rel.get("body") or "")[:4000]
                info.published = rel.get("published_at", "")
                asset = next((a for a in rel.get("assets", []) if ASSET_RE.match(a.get("name", ""))), None)
                if asset:
                    info.asset_id, info.asset_name = asset["id"], asset["name"]
                    info.size, info.digest = asset.get("size", 0), asset.get("digest") or ""
                info.available = bool(asset) and is_newer(info.latest)
        if info.error:
            log.warning("Update-Prüfung: %s", info.error)
        elif info.available:
            log.info("Update verfügbar: %s → %s", __version__, info.latest)
        self.info = info
        return info

    def check_due(self) -> bool:
        """True, wenn eine automatische Prüfung ansteht (merkt sich den Zeitpunkt sofort)."""
        if self.state != "idle" or time.time() - self.info.checked_at < CHECK_INTERVAL_S:
            return False
        self.info.checked_at = time.time()
        return True

    # ---------- Laden & Installieren
    def _download(self, info: UpdateInfo, repo: str, token: str) -> Path:
        target = sub_dir("updates") / info.asset_name
        tmp = target.with_suffix(".part")
        url = f"{API}/repos/{repo}/releases/assets/{info.asset_id}"
        sha = hashlib.sha256()
        with requests.get(url, headers=self._headers(token, binary=True), stream=True, timeout=60) as r:
            if not r.ok:
                raise UpdateError(f"Download fehlgeschlagen ({r.status_code})")
            total = int(r.headers.get("content-length") or info.size or 0)
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    self.progress = int(done * 100 / total) if total else 0
        if info.digest.startswith("sha256:") and sha.hexdigest() != info.digest.split(":", 1)[1].lower():
            tmp.unlink(missing_ok=True)
            raise UpdateError("Prüfsumme des Installers stimmt nicht – Download verworfen")
        if info.size and tmp.stat().st_size != info.size:
            tmp.unlink(missing_ok=True)
            raise UpdateError("Installer unvollständig heruntergeladen")
        tmp.replace(target)
        return target

    def _launch_installer(self, setup: Path) -> None:
        """Startet den Installer losgelöst: er beendet OCRDMS, aktualisiert und startet es neu."""
        args = [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                f"/LOG={sub_dir('updates') / 'update-install.log'}"]
        if not getattr(sys, "frozen", False):
            raise UpdateError("Updates können nur in der installierten Version eingespielt werden")
        flags = 0x00000008 | 0x00000200 | 0x01000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | BREAKAWAY_FROM_JOB
        try:
            subprocess.Popen(args, creationflags=flags, close_fds=True, cwd=str(setup.parent))
        except OSError as e:
            if getattr(e, "winerror", None) != 740:  # 740 = Adminrechte erforderlich
                raise
            # Infobereich-Betrieb als normaler Benutzer: Installer mit UAC-Abfrage starten
            import ctypes
            params = subprocess.list2cmdline(args[1:])
            if ctypes.windll.shell32.ShellExecuteW(None, "runas", str(setup), params, str(setup.parent), 0) <= 32:
                raise UpdateError("Installer konnte nicht mit Administratorrechten gestartet werden")

    def install(self) -> None:
        """Lädt und startet das Update im Hintergrund. Status über `state`/`progress`."""
        with self._lock:
            if self.state in ("downloading", "installing"):
                return
            self.state, self.progress = "downloading", 0
        threading.Thread(target=self._install, daemon=True, name="ocrdms-update").start()

    def _install(self) -> None:
        repo, token = self.get_config()
        try:
            info = self.check()
            if not info.available:
                raise UpdateError(info.error or "Kein neueres Update vorhanden")
            log.info("Lade Update %s …", info.latest)
            setup = self._download(info, repo, token)
            self.state = "installing"
            log.info("Starte Installation von %s – OCRDMS wird gleich neu gestartet", info.latest)
            self._launch_installer(setup)
        except Exception as e:
            log.error("Update fehlgeschlagen: %s", e)
            self.info.error = str(e)
            self.state = "error"

    def status(self) -> dict:
        return {**asdict(self.info), "state": self.state, "progress": self.progress,
                "frozen": bool(getattr(sys, "frozen", False))}


def cleanup_old_downloads() -> None:
    folder = sub_dir("updates")
    for f in folder.glob("OCRDMS-Setup-*.exe"):
        try:
            if time.time() - f.stat().st_mtime > 3600:
                os.remove(f)
        except OSError:
            pass
