"""FastAPI-Anwendung: Weboberfläche, REST-API, Upload und Handy-Scan."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import asdict, fields
from pathlib import Path

import pymupdf
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import APP_NAME, __version__, auth
from .certs import ca_cert_path, local_names
from .config import (
    DEFAULT_DOCUMENT_TYPES, DEFAULT_TAG_DESCRIPTIONS, DEFAULT_TAGS, SCOPE_TAGS, ServerConfig, Settings, Taxonomy,
    load_server_config, save_server_config,
)
from .engine import Engine
from .ollama_client import OllamaClient, OllamaError
from .paths import static_dir, sub_dir
from .pipeline import SINGLE_SUBDIR, safe_filename, unique_path
from .scan import MODES, ScanStore, images_to_pdf, thumbnail

log = logging.getLogger(__name__)

MAX_UPLOAD = 200 * 1024 * 1024
_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


class PasswordIn(BaseModel):
    password: str


class PasswordChange(BaseModel):
    old: str
    new: str


class AutoIn(BaseModel):
    on: bool


class OllamaTest(BaseModel):
    url: str
    model: str = ""


class FinishScan(BaseModel):
    single: bool = True
    name: str = ""


class OrderIn(BaseModel):
    order: list[str]


class ModeIn(BaseModel):
    mode: str = "auto"
    original: bool = False


def require_login(request: Request) -> None:
    if not request.session.get("user"):
        raise HTTPException(401, "Nicht angemeldet")


def _mark_ready(path: Path) -> None:
    """Datei sofort als „fertig geschrieben“ markieren (sonst wartet die Pipeline auf Stabilität)."""
    old = time.time() - 120
    os.utime(path, (old, old))


def create_app(engine: Engine, server: ServerConfig | None = None) -> FastAPI:
    server = server or load_server_config()
    app = FastAPI(title=APP_NAME, version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=auth.session_secret(), session_cookie="ocrdms_session",
                       max_age=30 * 24 * 3600, same_site="strict", https_only=server.https)
    scans = ScanStore(sub_dir("scan_tmp"))
    protected = [Depends(require_login)]

    # ------------------------------------------------------------ öffentlich
    @app.get("/", include_in_schema=False)
    def index():
        # Versionskennung an CSS/JS hängen, damit Browser nach Updates keine alten Dateien verwenden
        html = (static_dir() / "index.html").read_text(encoding="utf-8")
        stamp = max(int(p.stat().st_mtime) for p in static_dir().iterdir())
        for asset in ("style.css", "app.js"):
            html = html.replace(f"/static/{asset}", f"/static/{asset}?v={__version__}-{stamp}")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    def health():
        return {"ok": True, "app": APP_NAME, "version": __version__}

    @app.get("/OCRDMS-CA.crt", include_in_schema=False)
    def ca_cert():
        if not ca_cert_path().exists():
            raise HTTPException(404, "HTTPS ist nicht aktiv")
        return FileResponse(ca_cert_path(), media_type="application/x-x509-ca-cert", filename="OCRDMS-CA.crt")

    @app.get("/api/auth")
    def auth_state(request: Request):
        return {"setup_required": not auth.password_is_set(), "logged_in": bool(request.session.get("user")),
                "version": __version__}

    @app.post("/api/auth/setup")
    def auth_setup(body: PasswordIn, request: Request):
        if auth.password_is_set():
            raise HTTPException(409, "Passwort ist bereits gesetzt")
        try:
            auth.set_password(body.password)
        except ValueError as e:
            raise HTTPException(400, str(e))
        request.session["user"] = "admin"
        log.info("Passwort eingerichtet")
        return {"ok": True}

    @app.post("/api/auth/login")
    def auth_login(body: PasswordIn, request: Request):
        if not auth.check_password(body.password):
            time.sleep(1.5)  # bremst Durchprobieren
            log.warning("Fehlgeschlagene Anmeldung von %s", request.client.host if request.client else "?")
            raise HTTPException(401, "Falsches Passwort")
        request.session["user"] = "admin"
        return {"ok": True}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        request.session.clear()
        return {"ok": True}

    @app.post("/api/auth/password", dependencies=protected)
    def auth_change(body: PasswordChange):
        if not auth.check_password(body.old):
            time.sleep(1.5)
            raise HTTPException(400, "Das bisherige Passwort ist falsch")
        try:
            auth.set_password(body.new)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    # ------------------------------------------------------------ Status & Steuerung
    @app.get("/api/status", dependencies=protected)
    def status():
        return engine.status()

    @app.post("/api/run", dependencies=protected)
    def run():
        return {"started": engine.run_now()}

    @app.post("/api/cancel", dependencies=protected)
    def cancel():
        engine.cancel()
        return {"ok": True}

    @app.post("/api/auto", dependencies=protected)
    def auto(body: AutoIn):
        engine.set_auto_run(body.on)
        return {"ok": True}

    @app.get("/api/log", dependencies=protected)
    def get_log(since: int = 0):
        return engine.log_buffer.since(since)

    # ------------------------------------------------------------ Dokumente
    def _output_file(rel: str) -> Path:
        base = Path(engine.settings.output_dir).resolve()
        path = (base / rel).resolve()
        if base not in path.parents or not path.is_file():
            raise HTTPException(404, "Datei nicht gefunden")
        return path

    @app.get("/api/documents", dependencies=protected)
    def documents():
        return engine.documents()

    @app.get("/api/files/pdf", dependencies=protected)
    def file_pdf(path: str, download: bool = False):
        p = _output_file(path)
        return FileResponse(p, media_type="application/pdf", filename=p.name,
                            content_disposition_type="attachment" if download else "inline")

    @app.get("/api/files/thumb", dependencies=protected)
    def file_thumb(path: str, page: int = 0, width: int = 300):
        p = _output_file(path)
        with pymupdf.open(p) as doc:
            if not 0 <= page < doc.page_count:
                raise HTTPException(404, "Seite nicht vorhanden")
            pg = doc[page]
            zoom = min(2.0, max(0.1, width / pg.rect.width))
            png = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    # ------------------------------------------------------------ Einstellungen
    def _public_settings() -> dict:
        data = asdict(engine.settings)
        data["github_token_set"] = bool(data.pop("github_token"))  # Token nie an den Browser ausliefern
        return data

    @app.get("/api/settings", dependencies=protected)
    def get_settings():
        return _public_settings()

    @app.put("/api/settings", dependencies=protected)
    def put_settings(body: dict):
        known = {f.name for f in fields(Settings)} - {"github_token"}
        data = {**asdict(engine.settings), **{k: v for k, v in body.items() if k in known}}
        if body.get("github_token"):  # leer = unverändert lassen
            data["github_token"] = str(body["github_token"]).strip()
        if body.get("github_token_clear"):
            data["github_token"] = ""
        try:
            s = Settings(**data)
            s.interval_minutes = max(1, min(1440, int(s.interval_minutes)))
            s.ocr_dpi = max(150, min(600, int(s.ocr_dpi)))
            s.review_confidence = max(0, min(100, int(s.review_confidence)))
            if s.review_mode not in ("auto", "pruefen"):
                raise ValueError("Ungültiger Prüfmodus")
            dirs = [Path(d).resolve() for d in (s.input_dir, s.output_dir, s.archive_dir, s.error_dir)]
            if any(not str(d).strip() for d in dirs) or len(set(dirs)) < 4:
                raise ValueError("Bitte vier unterschiedliche Ordner angeben")
            if s.github_repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", s.github_repo.strip()):
                raise ValueError("GitHub-Repository bitte als „Besitzer/Name“ angeben")
            engine.update_settings(s)
        except (ValueError, TypeError, OSError) as e:
            raise HTTPException(400, str(e))
        return _public_settings()

    # ------------------------------------------------------------ Updates
    @app.get("/api/update", dependencies=protected)
    def update_status():
        return engine.updater.status()

    @app.post("/api/update/check", dependencies=protected)
    def update_check():
        engine.updater.check()
        return engine.updater.status()

    @app.post("/api/update/install", dependencies=protected)
    def update_install():
        if engine.busy:
            raise HTTPException(409, "Bitte warten, bis die laufende Verarbeitung abgeschlossen ist")
        engine.updater.install()
        return engine.updater.status()

    @app.get("/api/server", dependencies=protected)
    def get_server(request: Request):
        names, ips = local_names()
        cfg = load_server_config()
        return {**asdict(cfg), "names": names, "ips": ips,
                "running_port": server.port, "running_https": server.https,
                "restart_needed": asdict(cfg) != asdict(server)}

    @app.put("/api/server", dependencies=protected)
    def put_server(body: dict):
        try:
            port = int(body.get("port", server.port))
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(400, "Ungültiger Port")
        cfg = ServerConfig(port=port, host=str(body.get("host") or "0.0.0.0"), https=bool(body.get("https", True)))
        save_server_config(cfg)
        return {"ok": True, "restart_needed": asdict(cfg) != asdict(server)}

    @app.get("/api/taxonomy", dependencies=protected)
    def get_taxonomy():
        return {**asdict(engine.taxonomy), "scope_tags": list(SCOPE_TAGS)}

    @app.get("/api/taxonomy/defaults", dependencies=protected)
    def taxonomy_defaults():
        return {"tags": DEFAULT_TAGS, "document_types": DEFAULT_DOCUMENT_TYPES,
                "tag_descriptions": DEFAULT_TAG_DESCRIPTIONS, "scope_tags": list(SCOPE_TAGS)}

    @app.put("/api/taxonomy", dependencies=protected)
    def put_taxonomy(body: dict):
        def clean(items):
            out = []
            for x in items or []:
                x = str(x).strip()
                if x and x not in out:
                    out.append(x)
            return out
        tags, types = clean(body.get("tags")), clean(body.get("document_types"))
        if not tags or not types:
            raise HTTPException(400, "Es wird mindestens ein Tag und ein Dokumenttyp benötigt")
        descs = {k: str(v).strip() for k, v in (body.get("tag_descriptions") or {}).items() if k in tags and str(v).strip()}
        engine.update_taxonomy(Taxonomy(tags, types, descs))
        return asdict(engine.taxonomy)

    @app.post("/api/ollama/test", dependencies=protected)
    def ollama_test(body: OllamaTest):
        try:
            models = OllamaClient(body.url, body.model).list_models()
        except OllamaError as e:
            return {"ok": False, "error": str(e), "models": []}
        return {"ok": True, "models": models, "model_installed": body.model in models}

    # ------------------------------------------------------------ Upload
    def _target_dir(single: bool) -> Path:
        d = Path(engine.settings.input_dir) / (SINGLE_SUBDIR if single else "")
        d.mkdir(parents=True, exist_ok=True)
        return d

    @app.post("/api/upload", dependencies=protected)
    async def upload(files: list[UploadFile] = File(...), single: bool = Form(False)):
        saved, images = [], []
        target = _target_dir(single)
        for f in files:
            name = f.filename or "upload"
            ext = Path(name).suffix.lower()
            data = await f.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, f"{name} ist zu groß (max. 200 MB)")
            if ext == ".pdf" or data[:5] == b"%PDF-":
                path = unique_path(target, safe_filename(Path(name).stem), ".pdf")
                path.write_bytes(data)
                _mark_ready(path)
                saved.append(path.name)
            elif ext in _IMAGE_TYPES:
                images.append((name, data))
            else:
                raise HTTPException(400, f"{name}: nur PDF- oder Bilddateien möglich")
        if images:  # Bilder einer Auswahl werden zu einer PDF zusammengefasst
            from .scan import decode_image, encode_jpeg
            pdf = images_to_pdf([encode_jpeg(decode_image(d), 90) for _, d in images])
            path = unique_path(target, safe_filename(Path(images[0][0]).stem), ".pdf")
            path.write_bytes(pdf)
            _mark_ready(path)
            saved.append(path.name)
        log.info("Hochgeladen: %s%s", ", ".join(saved), " (Einzeldokument)" if single else "")
        engine.run_now()
        return {"saved": saved}

    # ------------------------------------------------------------ Handy-Scan
    def _page_json(sid, p):
        return {"id": p.id, "detected": p.detected, "mode": p.mode,
                "thumb": f"/api/scan/{sid}/page/{p.id}.jpg?thumb=1&t={int(p.processed.stat().st_mtime * 1000)}",
                "full": f"/api/scan/{sid}/page/{p.id}.jpg?t={int(p.processed.stat().st_mtime * 1000)}"}

    def _session(sid):
        try:
            return scans.get(sid)
        except KeyError:
            raise HTTPException(404, "Scan-Sitzung abgelaufen – bitte neu beginnen")

    @app.post("/api/scan", dependencies=protected)
    def scan_new():
        return {"id": scans.create().id}

    @app.get("/api/scan/{sid}", dependencies=protected)
    def scan_get(sid: str):
        s = _session(sid)
        return {"id": sid, "pages": [_page_json(sid, p) for p in s.pages]}

    @app.post("/api/scan/{sid}/photo", dependencies=protected)
    async def scan_photo(sid: str, file: UploadFile = File(...), mode: str = Form("auto")):
        _session(sid)
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > 50 * 1024 * 1024:
            raise HTTPException(413, "Foto zu groß")
        if mode not in MODES:
            mode = "auto"
        try:
            from starlette.concurrency import run_in_threadpool
            page = await run_in_threadpool(scans.add_photo, sid, data, mode)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _page_json(sid, page)

    @app.get("/api/scan/{sid}/page/{pid}.jpg", dependencies=protected)
    def scan_image(sid: str, pid: str, thumb: bool = False):
        _session(sid)
        try:
            p = scans.page(sid, pid)
        except KeyError:
            raise HTTPException(404, "Seite nicht gefunden")
        data = p.processed.read_bytes()
        return Response(thumbnail(data) if thumb else data, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=600"})

    @app.post("/api/scan/{sid}/page/{pid}/rotate", dependencies=protected)
    def scan_rotate(sid: str, pid: str, cw: bool = True):
        _session(sid)
        try:
            return _page_json(sid, scans.rotate(sid, pid, cw))
        except KeyError:
            raise HTTPException(404, "Seite nicht gefunden")

    @app.post("/api/scan/{sid}/page/{pid}/mode", dependencies=protected)
    def scan_mode(sid: str, pid: str, body: ModeIn):
        _session(sid)
        try:
            return _page_json(sid, scans.reprocess(sid, pid, body.mode if body.mode in MODES else "auto", body.original))
        except KeyError:
            raise HTTPException(404, "Seite nicht gefunden")

    @app.delete("/api/scan/{sid}/page/{pid}", dependencies=protected)
    def scan_delete_page(sid: str, pid: str):
        _session(sid)
        try:
            scans.delete_page(sid, pid)
        except KeyError:
            raise HTTPException(404, "Seite nicht gefunden")
        return {"ok": True}

    @app.post("/api/scan/{sid}/order", dependencies=protected)
    def scan_order(sid: str, body: OrderIn):
        _session(sid)
        try:
            scans.reorder(sid, body.order)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/scan/{sid}/finish", dependencies=protected)
    def scan_finish(sid: str, body: FinishScan):
        _session(sid)
        try:
            pdf = scans.finish(sid)
        except ValueError as e:
            raise HTTPException(400, str(e))
        stem = safe_filename(body.name) if body.name.strip() else time.strftime("Handyscan_%Y-%m-%d_%H-%M-%S")
        path = unique_path(_target_dir(body.single), stem, ".pdf")
        path.write_bytes(pdf)
        _mark_ready(path)
        log.info("Handy-Scan gespeichert: %s%s", path.name, " (Einzeldokument)" if body.single else "")
        engine.run_now()
        return {"saved": path.name}

    @app.delete("/api/scan/{sid}", dependencies=protected)
    def scan_discard(sid: str):
        scans.discard(sid)
        return {"ok": True}

    # ------------------------------------------------------------ statische Dateien
    app.mount("/static", StaticFiles(directory=static_dir()), name="static")

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app

