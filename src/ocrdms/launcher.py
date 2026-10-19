"""Starter ohne Konsolenfenster: startet den Server (falls nicht schon als Dienst aktiv),
öffnet den Browser und zeigt ein Symbol im Infobereich."""

from __future__ import annotations

import ctypes
import logging
import time
import webbrowser

import requests
import urllib3

from . import APP_NAME
from .certs import local_names
from .config import load_server_config
from .logsetup import setup_logging
from .server import OcrdmsServer, server_url

log = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def message_box(text: str, error: bool = False) -> None:
    flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
    ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, flags)


def server_running(url: str) -> bool:
    try:
        r = requests.get(f"{url}/api/health", timeout=2, verify=False)
        return r.ok and r.json().get("app") == APP_NAME
    except (requests.RequestException, ValueError):
        return False


def _tray_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(12, 4), (40, 4), (52, 16), (52, 60), (12, 60)], fill="#2563eb")
    d.polygon([(40, 4), (40, 16), (52, 16)], fill="#93c5fd")
    for i, w in enumerate((28, 22, 26)):
        d.rounded_rectangle([18, 24 + i * 8, 18 + w, 27 + i * 8], 2, fill="white")
    d.ellipse([36, 44, 54, 62], fill="#10b981")
    return img


def run_launcher() -> int:
    setup_logging()
    cfg = load_server_config()
    url = server_url(cfg)

    if server_running(url):  # läuft bereits (Dienst oder anderer Start) → nur Browser öffnen
        webbrowser.open(url)
        return 0

    try:
        srv = OcrdmsServer(cfg)
    except Exception as e:
        log.exception("Start fehlgeschlagen")
        message_box(f"{APP_NAME} konnte nicht gestartet werden:\n{e}", error=True)
        return 1
    thread = srv.start_in_thread()
    for _ in range(300):
        if srv.server.started or not thread.is_alive():
            break
        time.sleep(0.1)
    if not srv.server.started:
        message_box(f"{APP_NAME} konnte den Webserver nicht starten.\n\n"
                    f"Ist Port {cfg.port} bereits belegt? Details im Protokoll unter %PROGRAMDATA%\\OCRDMS\\logs.",
                    error=True)
        return 1
    webbrowser.open(url)

    import pystray

    _, ips = local_names()
    lan_ip = next((ip for ip in ips if not ip.startswith("127.")), "localhost")

    def on_open(icon, item):
        webbrowser.open(url)

    def on_quit(icon, item):
        icon.visible = False
        srv.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("OCRDMS öffnen", on_open, default=True),
        pystray.MenuItem(f"Im Netz: {server_url(cfg, lan_ip)}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Beenden", on_quit),
    )
    icon = pystray.Icon(APP_NAME, _tray_image(), f"{APP_NAME} – {server_url(cfg, lan_ip)}", menu)
    icon.run()
    return 0
