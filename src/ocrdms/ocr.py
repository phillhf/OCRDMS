"""Seitenanalyse: Leerseiten erkennen, Ausrichtung korrigieren, OCR mit unsichtbarer Textebene.

Verwendet die in PyMuPDF eingebaute Tesseract-Engine – benötigt nur die mitgelieferten
Sprachdaten (resources/tessdata), keine separate Tesseract-Installation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from .paths import tessdata_dir

_LIGHT_BYTES = bytes(range(140, 256))
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_VOWELS = set("aeiouyäöüAEIOUYÄÖÜ")
_FONT = None


def _font() -> pymupdf.Font:
    global _FONT
    if _FONT is None:
        _FONT = pymupdf.Font("helv")
    return _FONT


@dataclass
class PageResult:
    text: str
    blank: bool = False
    ocr_used: bool = False
    rotated_by: int = 0
    quality: float = 0.0


def text_quality(text: str) -> float:
    """Anteil plausibler Wörter (≥3 Buchstaben mit Vokal) – grobes Maß für brauchbaren OCR-Text."""
    words = _WORD_RE.findall(text)
    if not words:
        return 0.0
    good = sum(1 for w in words if len(w) >= 3 and w.isalpha() and any(c in _VOWELS for c in w))
    return good / len(words)


def ink_ratio(page: pymupdf.Page, dpi: int = 40, margin: float = 0.06) -> float:
    """Anteil dunkler Pixel ohne Randbereich (Scannerkanten, Lochungen)."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    w, h, stride, s = pix.width, pix.height, pix.stride, pix.samples
    mx, my = int(w * margin), int(h * margin)
    dark = total = 0
    for y in range(my, h - my):
        row = s[y * stride + mx: y * stride + w - mx]
        total += len(row)
        dark += len(row.translate(None, _LIGHT_BYTES))
    return dark / total if total else 0.0


def _ocr_text(page: pymupdf.Page, language: str, dpi: int) -> tuple[str, pymupdf.TextPage]:
    tp = page.get_textpage_ocr(language=language, dpi=dpi, full=True, tessdata=str(tessdata_dir()))
    return page.get_text(textpage=tp), tp


def is_blank(page: pymupdf.Page, threshold: float, language: str) -> bool:
    if len(page.get_text().strip()) > 20:
        return False
    if ink_ratio(page) >= threshold:
        return False
    # Wenig Tinte – zur Sicherheit kurz lesen, damit Seiten mit nur einer Zeile nicht verloren gehen.
    text, _ = _ocr_text(page, language, 150)
    good = [w for w in _WORD_RE.findall(text) if len(w) >= 3 and w.isalpha()]
    return len(good) < 3


def _add_text_layer(page: pymupdf.Page, tp: pymupdf.TextPage) -> None:
    font = _font()
    tw = pymupdf.TextWriter(page.rect)
    for x0, y0, x1, y1, word, *_ in page.get_text("words", textpage=tp):
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            continue
        unit = font.text_length(word, fontsize=1)
        fs = min(w / unit if unit > 0 else h, h * 1.3)
        if fs < 1:
            continue
        tw.append((x0, y1 - 0.2 * h), word, font=font, fontsize=fs)
    tw.write_text(page, render_mode=3)  # 3 = unsichtbar, aber durchsuchbar/markierbar


def _best_rotation(page: pymupdf.Page, language: str, current_quality: float) -> int:
    best_rot, best_q = 0, current_quality
    for rot in (180, 90, 270):
        page.set_rotation(rot)
        text, _ = _ocr_text(page, language, 150)
        q = text_quality(text)
        if q > best_q + 0.15 and len(text.strip()) > 40:
            best_rot, best_q = rot, q
    page.set_rotation(0)
    return best_rot


def process_page(page: pymupdf.Page, language: str = "deu", dpi: int = 300,
                 detect_blank: bool = True, blank_threshold: float = 0.004) -> PageResult:
    """Analysiert eine Seite in-place: ggf. drehen, OCR-Textebene einfügen, Text zurückgeben."""
    if page.rotation:
        page.remove_rotation()

    existing = page.get_text().strip()
    if len(existing) > 100 and text_quality(existing) >= 0.5:
        return PageResult(text=existing, quality=text_quality(existing))

    if detect_blank and is_blank(page, blank_threshold, language):
        return PageResult(text="", blank=True)

    text, tp = _ocr_text(page, language, dpi)
    quality = text_quality(text)
    rotated = 0
    if quality < 0.5:
        rotated = _best_rotation(page, language, quality)
        if rotated:
            page.set_rotation(rotated)
            page.remove_rotation()
            text, tp = _ocr_text(page, language, dpi)
            quality = text_quality(text)

    if text.strip():
        _add_text_layer(page, tp)
    return PageResult(text=text, ocr_used=True, rotated_by=rotated, quality=quality)
