"""Windows-Dienst „OCRDMS“ (optional). Verwaltung: `ocrdms service install|start|stop|remove`."""

from __future__ import annotations

import logging
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

from .logsetup import setup_logging

SERVICE_NAME = "OCRDMS"


class OcrdmsService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = "OCRDMS Dokumentenverarbeitung"
    _svc_description_ = "Trennt, erkennt (OCR) und verschlagwortet eingescannte PDF-Dokumente; Weboberfläche für Browser und Handy."

    if getattr(sys, "frozen", False):
        _exe_name_ = sys.executable
        _exe_args_ = "service-run"

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.srv = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        setup_logging()
        from .server import OcrdmsServer
        log = logging.getLogger(__name__)
        try:
            self.srv = OcrdmsServer()
            self.srv.start_in_thread()
            log.info("Dienst gestartet")
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        except Exception:
            log.exception("Dienst-Fehler")
            raise
        finally:
            if self.srv:
                self.srv.stop()
            log.info("Dienst beendet")


def run_from_scm() -> None:
    """Einstieg, wenn der Dienststeuerungs-Manager die EXE startet."""
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(OcrdmsService)
    servicemanager.StartServiceCtrlDispatcher()


def manage(args: list[str]) -> int:
    """install | start | stop | remove | restart – wie win32serviceutil, Start automatisch."""
    argv = [sys.argv[0]]
    if args and args[0] == "install":
        argv += ["--startup", "auto"]
    win32serviceutil.HandleCommandLine(OcrdmsService, argv=argv + args)
    return 0
