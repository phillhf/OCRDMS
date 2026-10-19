"""Handy-Fotos zu sauberen Scan-Seiten aufbereiten und zu einer PDF zusammenfügen.

Ablauf je Foto: Dokumentkanten finden → perspektivisch entzerren → Kontrast/Hintergrund bereinigen.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pymupdf

log = logging.getLogger(__name__)

MAX_SIDE = 2400  # entspricht ca. 290 dpi bei A4 – reicht für OCR, hält Dateien klein
MODES = ("auto", "sw", "grau", "farbe")


def decode_image(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)  # berücksichtigt EXIF-Drehung
    if img is None:
        raise ValueError("Bild konnte nicht gelesen werden")
    return img


def _order_corners(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype("float32")
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def find_document(img: np.ndarray) -> np.ndarray | None:
    """Liefert die vier Ecken des Blatts (oben-links, oben-rechts, unten-rechts, unten-links) oder None."""
    h, w = img.shape[:2]
    scale = 800 / max(h, w)
    small = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    # Text „wegschließen“, damit nur die Blattkante übrig bleibt
    gray = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    edges = cv2.Canny(gray, 30, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    min_area = 0.2 * small.shape[0] * small.shape[1]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx) and cv2.contourArea(approx) > min_area:
            return _order_corners(approx) / scale
    return None


def warp(img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    m = cv2.getPerspectiveTransform(corners.astype("float32"), dst)
    return cv2.warpPerspective(img, m, (width, height), flags=cv2.INTER_CUBIC)


def _limit_size(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) <= MAX_SIDE:
        return img
    f = MAX_SIDE / max(h, w)
    return cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)


def _flatten_background(gray: np.ndarray) -> np.ndarray:
    """Schatten und ungleichmäßige Beleuchtung entfernen: durch geschätzten Hintergrund teilen."""
    k = max(15, (min(gray.shape) // 25) | 1)
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (k, k), 0)
    norm = cv2.divide(gray, bg, scale=255)
    return cv2.normalize(norm, None, 0, 255, cv2.NORM_MINMAX)


def enhance(img: np.ndarray, mode: str) -> np.ndarray:
    if mode == "farbe":
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
        return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    gray = _flatten_background(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    if mode == "sw":
        return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    # grau / auto: Papier weiß, Schrift kräftig, Graustufen bleiben erhalten (Stempel, Unterschriften)
    lut = np.clip((np.arange(256) - 40) * 255.0 / 175.0, 0, 255).astype(np.uint8)
    return cv2.LUT(gray, lut)


def process_photo(data: bytes, mode: str = "auto") -> tuple[np.ndarray, bool]:
    """Gibt (aufbereitetes Bild, Blatt erkannt?) zurück."""
    img = decode_image(data)
    corners = find_document(img)
    if corners is not None:
        img = warp(img, corners)
    img = _limit_size(img)
    return enhance(img, mode if mode in MODES else "auto"), corners is not None


def encode_jpeg(img: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG-Kodierung fehlgeschlagen")
    return buf.tobytes()


def thumbnail(jpeg: bytes, max_side: int = 400) -> bytes:
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_UNCHANGED)
    h, w = img.shape[:2]
    f = max_side / max(h, w)
    return encode_jpeg(cv2.resize(img, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA), 70)


def images_to_pdf(pages: list[bytes]) -> bytes:
    """JPEG-Seiten → PDF; Seitenbreite A4, Höhe proportional."""
    doc = pymupdf.open()
    for jpeg in pages:
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_UNCHANGED)
        h, w = img.shape[:2]
        width = 595.0
        page = doc.new_page(width=width, height=width * h / w)
        page.insert_image(page.rect, stream=jpeg)
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


# ---------------------------------------------------------------- Scan-Sitzungen

@dataclass
class ScanPage:
    id: str
    original: Path
    processed: Path
    detected: bool
    mode: str


@dataclass
class ScanSession:
    id: str
    folder: Path
    pages: list[ScanPage] = field(default_factory=list)


class ScanStore:
    """Zwischenspeicher für laufende Handy-Scans (auf der Platte, damit große Fotos nicht im RAM liegen)."""

    def __init__(self, root: Path):
        self.root = root
        shutil.rmtree(root, ignore_errors=True)  # Reste alter Sitzungen verwerfen
        root.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, ScanSession] = {}

    def create(self) -> ScanSession:
        sid = uuid.uuid4().hex
        s = ScanSession(sid, self.root / sid)
        s.folder.mkdir()
        self.sessions[sid] = s
        return s

    def get(self, sid: str) -> ScanSession:
        if sid not in self.sessions:
            raise KeyError(sid)
        return self.sessions[sid]

    def page(self, sid: str, pid: str) -> ScanPage:
        for p in self.get(sid).pages:
            if p.id == pid:
                return p
        raise KeyError(pid)

    def add_photo(self, sid: str, data: bytes, mode: str) -> ScanPage:
        s = self.get(sid)
        pid = uuid.uuid4().hex[:12]
        original = s.folder / f"{pid}_orig.jpg"
        original.write_bytes(data)
        img, detected = process_photo(data, mode)
        processed = s.folder / f"{pid}.jpg"
        processed.write_bytes(encode_jpeg(img))
        page = ScanPage(pid, original, processed, detected, mode)
        s.pages.append(page)
        return page

    def reprocess(self, sid: str, pid: str, mode: str, use_original: bool = False) -> ScanPage:
        p = self.page(sid, pid)
        data = p.original.read_bytes()
        if use_original:
            img = _limit_size(decode_image(data))
            p.detected = False
        else:
            img, p.detected = process_photo(data, mode)
        p.mode = mode
        p.processed.write_bytes(encode_jpeg(img))
        return p

    def rotate(self, sid: str, pid: str, clockwise: bool = True) -> ScanPage:
        p = self.page(sid, pid)
        img = cv2.imdecode(np.frombuffer(p.processed.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE if clockwise else cv2.ROTATE_90_COUNTERCLOCKWISE)
        p.processed.write_bytes(encode_jpeg(img))
        orig = decode_image(p.original.read_bytes())  # Original mitdrehen, damit Neuberechnung passt
        orig = cv2.rotate(orig, cv2.ROTATE_90_CLOCKWISE if clockwise else cv2.ROTATE_90_COUNTERCLOCKWISE)
        p.original.write_bytes(encode_jpeg(orig, 90))
        return p

    def delete_page(self, sid: str, pid: str) -> None:
        s = self.get(sid)
        p = self.page(sid, pid)
        s.pages.remove(p)
        p.original.unlink(missing_ok=True)
        p.processed.unlink(missing_ok=True)

    def reorder(self, sid: str, order: list[str]) -> None:
        s = self.get(sid)
        by_id = {p.id: p for p in s.pages}
        if sorted(order) != sorted(by_id):
            raise ValueError("Reihenfolge passt nicht zu den Seiten")
        s.pages = [by_id[i] for i in order]

    def finish(self, sid: str) -> bytes:
        s = self.get(sid)
        if not s.pages:
            raise ValueError("Keine Seiten vorhanden")
        pdf = images_to_pdf([p.processed.read_bytes() for p in s.pages])
        self.discard(sid)
        return pdf

    def discard(self, sid: str) -> None:
        s = self.sessions.pop(sid, None)
        if s:
            shutil.rmtree(s.folder, ignore_errors=True)
