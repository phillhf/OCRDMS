"""Hintergrund-Verarbeitung für den Server: Zeitplan, Status, Protokollpuffer."""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path

from .config import Settings, Taxonomy, load_settings, load_taxonomy, save_settings, save_taxonomy
from .ollama_client import OllamaError
from .pipeline import REVIEW_SUBDIR, Pipeline
from .updater import Updater, cleanup_old_downloads

log = logging.getLogger(__name__)


class BufferHandler(logging.Handler):
    """Hält die letzten Protokollzeilen für die Weboberfläche vor."""

    def __init__(self, size: int = 500):
        super().__init__(logging.INFO)
        self.lines: deque[dict] = deque(maxlen=size)
        self.counter = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self.counter += 1
            self.lines.append({"id": self.counter, "time": time.strftime("%d.%m. %H:%M:%S", time.localtime(record.created)),
                               "level": record.levelname, "text": record.getMessage()})

    def since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [line for line in self.lines if line["id"] > last_id]


class Engine:
    def __init__(self):
        self.settings: Settings = load_settings()
        self.taxonomy: Taxonomy = load_taxonomy()
        self.settings.ensure_dirs()
        self.log_buffer = BufferHandler()
        logging.getLogger().addHandler(self.log_buffer)

        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._scheduler: threading.Thread | None = None

        self.next_run_at = time.time() + 5
        self.progress: dict | None = None
        self.last_error = ""
        self.last_run_at: float | None = None
        self.updater = Updater(lambda: (self.settings.github_repo.strip(), self.settings.github_token.strip()))

    # ---------- Lebenszyklus
    def start(self) -> None:
        self._scheduler = threading.Thread(target=self._schedule_loop, daemon=True, name="ocrdms-scheduler")
        self._scheduler.start()

    def stop(self) -> None:
        self._stop.set()
        self._cancel.set()
        self._wake.set()
        if self._worker:
            self._worker.join(timeout=10)
        logging.getLogger().removeHandler(self.log_buffer)

    def _schedule_loop(self) -> None:
        cleanup_old_downloads()
        while not self._stop.is_set():
            if self.settings.update_check and self.updater.check_due():
                threading.Thread(target=self.updater.check, daemon=True, name="ocrdms-update-check").start()
            if self.settings.auto_run and time.time() >= self.next_run_at:
                self.run_now()
            self._wake.wait(1)
            self._wake.clear()

    # ---------- Steuerung
    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def run_now(self) -> bool:
        with self._lock:
            if self.busy:
                return False
            self._cancel.clear()
            s, t = copy.deepcopy(self.settings), copy.deepcopy(self.taxonomy)
            self.progress = {"file": "", "stage": "Suche nach neuen Dateien", "current": 0, "total": 0}
            self._worker = threading.Thread(target=self._run, args=(s, t), daemon=True, name="ocrdms-pipeline")
            self._worker.start()
            return True

    def cancel(self) -> None:
        self._cancel.set()

    def set_auto_run(self, on: bool) -> None:
        self.settings.auto_run = on
        save_settings(self.settings)
        if on:
            self.next_run_at = min(self.next_run_at, time.time() + 2)

    def update_settings(self, s: Settings) -> None:
        s.ensure_dirs()
        save_settings(s)
        self.settings = s
        self.next_run_at = time.time() + 2

    def update_taxonomy(self, t: Taxonomy) -> None:
        save_taxonomy(t)
        self.taxonomy = t

    def _on_event(self, kind: str, data: dict) -> None:
        if kind == "progress":
            self.progress = data

    def _run(self, s: Settings, t: Taxonomy) -> None:
        self.last_error = ""
        try:
            Pipeline(s, t, self._on_event, self._cancel).run_once()
        except OllamaError as e:
            self.last_error = str(e)
            log.error("%s", e)
        except Exception as e:
            self.last_error = str(e)
            log.exception("Unerwarteter Fehler")
        finally:
            self.progress = None
            self.last_run_at = time.time()
            self.next_run_at = time.time() + self.settings.interval_minutes * 60

    # ---------- Abfragen
    def status(self) -> dict:
        return {
            "busy": self.busy,
            "auto_run": self.settings.auto_run,
            "next_run_in": max(0, int(self.next_run_at - time.time())) if self.settings.auto_run and not self.busy else None,
            "progress": self.progress,
            "last_error": self.last_error,
            "pending": self._count_pending(),
            "review": len(list((Path(self.settings.output_dir) / REVIEW_SUBDIR).glob("*.pdf"))),
            "update": {"available": self.updater.info.available, "latest": self.updater.info.latest,
                       "state": self.updater.state, "progress": self.updater.progress},
        }

    def _count_pending(self) -> int:
        inp = Path(self.settings.input_dir)
        try:
            return sum(1 for f in inp.rglob("*.pdf") if f.is_file())
        except OSError:
            return 0

    def documents(self, limit: int = 200) -> list[dict]:
        out = Path(self.settings.output_dir)
        files = list(out.glob("*.json")) + list((out / REVIEW_SUBDIR).glob("*.json"))
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        docs = []
        for f in files[:limit]:
            try:
                info = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pdf = f.with_suffix(".pdf")
            if not pdf.exists():
                continue
            info["pfad"] = pdf.relative_to(out).as_posix()
            docs.append(info)
        return docs
