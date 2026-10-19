"""Verarbeitungsablauf: Eingang scannen → OCR → trennen → verschlagworten → ablegen."""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

import pymupdf

from . import __version__
from .classifier import DocumentMeta, classify
from .config import Settings, Taxonomy
from .ocr import process_page
from .ollama_client import OllamaClient, OllamaError
from .splitter import Boundary, DocumentGroup, group_is_uncertain, split_pages

log = logging.getLogger(__name__)

WORK_SUBDIR = "_in_Arbeit"
REVIEW_SUBDIR = "_Pruefen"
SINGLE_SUBDIR = "Einzeldokument"  # Dateien hier werden nicht getrennt (z. B. Handy-Scans)
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

EventCallback = Callable[[str, dict], None]


def safe_filename(text: str, max_len: int = 120) -> str:
    text = _INVALID_CHARS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:max_len].rstrip(" .") or "Dokument"


def build_filename(meta: DocumentMeta) -> str:
    """JJJJ-MM-TT_Korrespondent_Titel – Absender wird nicht doppelt aufgeführt."""
    title = meta.titel
    if meta.korrespondent:
        title = re.sub(re.escape(meta.korrespondent), "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s+", " ", title).strip(" -–,") or meta.dokumenttyp
    parts = [meta.datum, meta.korrespondent, title]
    return safe_filename("_".join(p for p in parts if p))


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    path = folder / f"{stem}{suffix}"
    n = 2
    while path.exists():
        path = folder / f"{stem} ({n}){suffix}"
        n += 1
    return path


def _move(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(dest_dir, src.stem, src.suffix)
    shutil.move(str(src), target)
    return target


class Pipeline:
    def __init__(self, settings: Settings, taxonomy: Taxonomy,
                 on_event: EventCallback | None = None, cancel: threading.Event | None = None):
        self.s = settings
        self.tax = taxonomy
        self.on_event = on_event or (lambda kind, data: None)
        self.cancel = cancel or threading.Event()
        self.client = OllamaClient(settings.ollama_url, settings.model, settings.llm_timeout_s)
        self._seen: dict[Path, tuple[int, float]] = {}

    # ---------- Eingang ----------

    def _is_ready(self, path: Path) -> bool:
        """Datei gilt als fertig geschrieben, wenn Größe/Zeit stabil sind und sie nicht gesperrt ist."""
        try:
            st = path.stat()
        except OSError:
            return False
        sig = (st.st_size, st.st_mtime)
        stable = self._seen.get(path) == sig or (time.time() - st.st_mtime) > 20
        self._seen[path] = sig
        if not stable or st.st_size == 0:
            return False
        try:
            with open(path, "rb+"):
                return True
        except OSError:
            return False

    def pending_files(self) -> list[Path]:
        inp = Path(self.s.input_dir)
        single = inp / SINGLE_SUBDIR
        single.mkdir(parents=True, exist_ok=True)
        # Liegengebliebenes aus einem Abbruch zuerst wieder aufnehmen
        for folder in (inp, single):
            work = folder / WORK_SUBDIR
            if work.exists():
                for f in work.iterdir():
                    if f.suffix.lower() == ".pdf":
                        _move(f, folder)
        files = [f for folder in (inp, single) for f in folder.iterdir()
                 if f.is_file() and f.suffix.lower() == ".pdf"]
        files.sort(key=lambda f: f.stat().st_mtime)
        return [f for f in files if self._is_ready(f)]

    def run_once(self) -> int:
        """Verarbeitet alle bereiten Dateien. Gibt die Zahl verarbeiteter Dateien zurück."""
        self.s.ensure_dirs()
        files = self.pending_files()
        if not files:
            return 0
        self.client.check()  # früh abbrechen, wenn Ollama fehlt – Dateien bleiben im Eingang
        done = 0
        for f in files:
            if self.cancel.is_set():
                break
            self.process_file(f)
            done += 1
        return done

    # ---------- Einzeldatei ----------

    def _progress(self, file: str, stage: str, cur: int, total: int) -> None:
        self.on_event("progress", {"file": file, "stage": stage, "current": cur, "total": total})

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise InterruptedError

    def process_file(self, path: Path) -> list[dict]:
        name = path.name
        origin = path.parent
        single = origin.name == SINGLE_SUBDIR
        work_path = _move(path, origin / WORK_SUBDIR)
        log.info("Verarbeite %s", name)
        started = time.time()
        try:
            results = self._process(work_path, name, single)
        except (InterruptedError, OllamaError) as e:
            _move(work_path, origin)
            if isinstance(e, InterruptedError):
                log.warning("Abgebrochen: %s bleibt im Eingang", name)
                return []
            log.error("%s – %s bleibt im Eingang und wird später erneut versucht", e, name)
            raise
        except Exception as e:
            log.exception("Fehler bei %s", name)
            target = _move(work_path, Path(self.s.error_dir))
            target.with_suffix(".fehler.txt").write_text(
                f"{datetime.now():%Y-%m-%d %H:%M:%S}\n{e}\n\n{traceback.format_exc()}", encoding="utf-8")
            self.on_event("file_failed", {"file": name, "error": str(e)})
            return []
        _move(work_path, Path(self.s.archive_dir))
        log.info("%s fertig: %d Dokument(e) in %.0f s", name, len(results), time.time() - started)
        self.on_event("file_done", {"file": name, "documents": len(results)})
        return results

    def _process(self, path: Path, name: str, single: bool = False) -> list[dict]:
        with pymupdf.open(path) as src:
            if src.needs_pass:
                raise ValueError("PDF ist passwortgeschützt")
            if src.page_count == 0:
                raise ValueError("PDF enthält keine Seiten")

            # 1. OCR je Seite (fügt unsichtbare Textebene direkt in die Seiten ein)
            page_info = []
            for i, page in enumerate(src):
                self._check_cancel()
                self._progress(name, "OCR", i + 1, src.page_count)
                r = process_page(page, self.s.ocr_language, self.s.ocr_dpi,
                                 self.s.remove_blank_pages, self.s.blank_ink_ratio)
                page_info.append(r)
                if r.blank:
                    log.info("Seite %d leer – wird entfernt", i + 1)
                elif r.rotated_by:
                    log.info("Seite %d um %d° gedreht", i + 1, r.rotated_by)
            ocr_bytes = src.tobytes(garbage=3, deflate=True)

        texts = {i: r.text for i, r in enumerate(page_info) if not r.blank}
        if not texts:
            raise ValueError("Alle Seiten sind leer")

        # 2. Trennen (entfällt bei Einzeldokumenten)
        if single:
            first = next(iter(texts))
            groups = [DocumentGroup(pages=list(texts), boundary=Boundary(first, True, 100, "einzeldokument"))]
        else:
            groups = split_pages(texts, self.client, self.s.review_confidence,
                                 progress=lambda c, t: self._progress(name, "Trennen", c, t),
                                 cancelled=self.cancel.is_set)
        log.info("%s: %d Seite(n) → %d Dokument(e)", name, len(texts), len(groups))

        # 3. Verschlagworten und ablegen
        out_dir = Path(self.s.output_dir)
        results = []
        with pymupdf.open(stream=ocr_bytes, filetype="pdf") as ocr_doc:
            for n, g in enumerate(groups, 1):
                self._check_cancel()
                self._progress(name, "Verschlagworten", n, len(groups))
                meta = classify(self.client, [texts[p] for p in g.pages], self.tax)
                review = self.s.review_mode == "pruefen" and group_is_uncertain(g, self.s.review_confidence)
                folder = out_dir / REVIEW_SUBDIR if review else out_dir
                folder.mkdir(parents=True, exist_ok=True)
                pdf_path = unique_path(folder, build_filename(meta), ".pdf")

                with pymupdf.open() as out:
                    for p in g.pages:
                        out.insert_pdf(ocr_doc, from_page=p, to_page=p)
                    out.set_metadata({
                        "title": meta.titel, "author": meta.korrespondent, "subject": meta.dokumenttyp,
                        "keywords": ", ".join(meta.tags), "creator": f"OCRDMS {__version__}",
                        "producer": "OCRDMS / PyMuPDF",
                    })
                    out.save(pdf_path, garbage=3, deflate=True)

                info = {
                    "datei": pdf_path.name,
                    "quelle": name,
                    "seiten_im_original": [p + 1 for p in g.pages],
                    "metadaten": meta.to_dict(),
                    "trennung": asdict(g.boundary) if g.boundary else None,
                    "unsichere_verknuepfungen": [asdict(b) for b in g.uncertain_links],
                    "pruefen": review,
                    "modell": self.s.model,
                    "verarbeitet_am": datetime.now().isoformat(timespec="seconds"),
                    "version": __version__,
                }
                pdf_path.with_suffix(".json").write_text(
                    json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
                log.info("→ %s%s [%s]", "PRÜFEN: " if review else "", pdf_path.name, ", ".join(meta.tags))
                self.on_event("document", info)
                results.append(info)
        return results
