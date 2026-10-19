"""Kommandozeile.

  ocrdms                       Starter: Server + Browser + Symbol im Infobereich (ohne Konsole)
  ocrdms serve [--port N]      Server im Vordergrund (Entwicklung/Fehlersuche)
  ocrdms once                  Eingang einmal verarbeiten und beenden
  ocrdms config --port N [--http|--https]   Netzwerk-Einstellungen setzen (z. B. durch den Installer)
  ocrdms service install|start|stop|remove  Windows-Dienst verwalten
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_server_config, load_settings, load_taxonomy, save_server_config, settings_path
from .logsetup import setup_logging


def run_cli(argv: list[str]) -> int:
    if argv and argv[0] == "service-run":
        from .service import run_from_scm
        run_from_scm()
        return 0
    if argv and argv[0] == "service":
        from .service import manage
        return manage(argv[1:])

    ap = argparse.ArgumentParser(prog="ocrdms", description="PDF-Stapel trennen, OCR und Tags vergeben")
    sub = ap.add_subparsers(dest="cmd")
    p_serve = sub.add_parser("serve", help="Server im Vordergrund starten")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--http", action="store_true", help="ohne HTTPS")
    p_once = sub.add_parser("once", help="Eingang einmal verarbeiten")
    p_once.add_argument("--eingang")
    p_once.add_argument("--ausgabe", help="Basisordner für Verarbeitet/Originale/Fehler")
    p_once.add_argument("--modell")
    p_cfg = sub.add_parser("config", help="Netzwerk-Einstellungen setzen")
    p_cfg.add_argument("--port", type=int)
    p_cfg.add_argument("--arbeitsordner", help="Basisordner für Eingang/Verarbeitet/Originale/Fehler "
                                               "(nur bei Erstinstallation, bestehende Einstellungen bleiben)")
    g = p_cfg.add_mutually_exclusive_group()
    g.add_argument("--http", action="store_true")
    g.add_argument("--https", action="store_true")
    args = ap.parse_args(argv)

    setup_logging()
    if args.cmd == "serve":
        from .server import OcrdmsServer
        cfg = load_server_config()
        if args.port:
            cfg.port = args.port
        if args.http:
            cfg.https = False
        OcrdmsServer(cfg).run()
        return 0
    if args.cmd == "config":
        cfg = load_server_config()
        if args.port:
            if not 1 <= args.port <= 65535:
                ap.error("Ungültiger Port")
            cfg.port = args.port
        if args.http or args.https:
            cfg.https = args.https
        save_server_config(cfg)
        if args.arbeitsordner and not settings_path().exists():
            from .config import Settings, save_settings
            base = Path(args.arbeitsordner)
            s = Settings(*(str(base / n) for n in ("Eingang", "Verarbeitet", "Originale", "Fehler")))
            s.ensure_dirs()
            save_settings(s)
        print(f"Port {cfg.port}, {'HTTPS' if cfg.https else 'HTTP'}")
        return 0
    if args.cmd == "once":
        from .pipeline import Pipeline
        s, tax = load_settings(), load_taxonomy()
        if args.eingang:
            s.input_dir = args.eingang
        if args.ausgabe:
            base = Path(args.ausgabe)
            s.output_dir, s.archive_dir, s.error_dir = (str(base / n) for n in ("Verarbeitet", "Originale", "Fehler"))
        if args.modell:
            s.model = args.modell
        n = Pipeline(s, tax).run_once()
        logging.getLogger("ocrdms").info("%d Datei(en) verarbeitet", n)
        return 0
    ap.print_help()
    return 0
