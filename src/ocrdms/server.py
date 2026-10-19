"""Startet den Webserver (für Konsole, Infobereich-Starter und Windows-Dienst gemeinsam)."""

from __future__ import annotations

import logging
import threading

import uvicorn

from .certs import ensure_server_cert
from .config import ServerConfig, load_server_config
from .engine import Engine
from .web import create_app

log = logging.getLogger(__name__)


def server_url(cfg: ServerConfig, host: str = "localhost") -> str:
    return f"{'https' if cfg.https else 'http'}://{host}:{cfg.port}"


class OcrdmsServer:
    """Kapselt Engine + Uvicorn, damit Starter und Dienst sauber starten/stoppen können."""

    def __init__(self, cfg: ServerConfig | None = None):
        self.cfg = cfg or load_server_config()
        self.engine = Engine()
        app = create_app(self.engine, self.cfg)
        kwargs = {}
        if self.cfg.https:
            crt, key = ensure_server_cert()
            kwargs = {"ssl_certfile": str(crt), "ssl_keyfile": str(key)}
        config = uvicorn.Config(app, host=self.cfg.host, port=self.cfg.port, log_config=None,
                                access_log=False, timeout_graceful_shutdown=5, **kwargs)
        self.server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    def run(self) -> None:
        """Blockiert, bis der Server beendet wird."""
        self.engine.start()
        log.info("Weboberfläche: %s", server_url(self.cfg))
        try:
            self.server.run()
        finally:
            self.engine.stop()
        if not self.server.started:
            raise RuntimeError(f"Server konnte nicht auf Port {self.cfg.port} starten (Port belegt?)")

    def start_in_thread(self) -> threading.Thread:
        self._thread = threading.Thread(target=self.run, daemon=True, name="ocrdms-web")
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self.server.should_exit = True
        if self._thread:
            self._thread.join(timeout=15)
