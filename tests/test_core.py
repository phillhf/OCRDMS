"""Schnelle Tests ohne Ollama (Sprachmodell wird durch Attrappen ersetzt)."""

import pymupdf
import pytest

from ocrdms.classifier import DocumentMeta, build_schema, validate
from ocrdms.config import Settings, Taxonomy
from ocrdms.ocr import process_page, text_quality
from ocrdms.pipeline import Pipeline, build_filename, safe_filename
from ocrdms.splitter import page_marker, rule_boundary, split_pages


def scanned_page(doc: pymupdf.Document, text: str, rotate: int = 0) -> pymupdf.Page:
    tmp = pymupdf.open()
    p = tmp.new_page(width=595, height=842)
    if text:
        p.insert_textbox(pymupdf.Rect(60, 60, 540, 780), text, fontsize=11)
    pix = p.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, pixmap=pix, rotate=rotate)
    return page


LETTER = ("Stadtwerke München GmbH\nHerrn Max Mustermann\nHauptstraße 5\n80331 München\n\n"
          "Ihre Jahresabrechnung für Strom und Gas\nSehr geehrter Herr Mustermann,\n"
          "anbei erhalten Sie die Abrechnung für den Zeitraum vom 01.01.2026 bis 31.12.2026.")


@pytest.mark.parametrize("text,expected", [
    ("Rechnung … Seite 2 von 3", (2, 3)),
    ("Blatt 1/4", (1, 4)),
    ("seite: 3 aus 3", (3, 3)),
    ("Seite 5 von 3", None),
    ("kein Marker 12/2026", None),
])
def test_page_marker(text, expected):
    assert page_marker(text) == expected


def test_rule_boundary():
    assert rule_boundary("Seite 1 von 2", "Seite 2 von 2")[0] is False
    assert rule_boundary("Seite 2 von 2", "irgendwas")[0] is True
    assert rule_boundary("Text", "Seite 1 von 3")[0] is True
    assert rule_boundary("Text", "mehr Text") is None


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def chat_json(self, system, user, schema):
        self.calls += 1
        return self.answers.pop(0)


def test_split_pages_rules_and_model():
    texts = {
        0: "A Seite 1 von 2", 1: "A Seite 2 von 2",
        2: "B Brief mit viel Text " * 5,
        3: "C neuer Brief mit viel Text " * 5,
        5: "C Fortsetzung mit viel Text " * 5,
    }
    client = FakeClient([
        {"neues_dokument": True, "sicherheit": 90, "begruendung": "neu"},
        {"neues_dokument": False, "sicherheit": 50, "begruendung": "unsicher"},
    ])
    groups = split_pages(texts, client, review_confidence=70)
    assert [g.pages for g in groups] == [[0, 1], [2], [3, 5]]
    assert client.calls == 2  # Seite 2 entschied die Regel „vorherige war letzte“
    assert groups[2].uncertain_links and groups[2].uncertain_links[0].confidence == 50


def test_validate_filters_unknown_values():
    tax = Taxonomy()
    meta = validate({"titel": "X", "dokumenttyp": "Erfunden", "bereich": "Privat",
                     "hauptthema": "Energie", "weiteres_thema": "keines",
                     "datum": "2026-02-30", "sicherheit": "abc"}, tax)
    assert meta.dokumenttyp == "Sonstiges"
    assert meta.tags == ["Privat", "Energie"]
    assert meta.datum == ""
    assert meta.sicherheit == 0
    schema = build_schema(tax)
    assert "Privat" not in schema["properties"]["hauptthema"]["enum"]


def test_filenames():
    meta = DocumentMeta(titel="Telekom Rechnung September", dokumenttyp="Rechnung",
                        korrespondent="Telekom", datum="2026-10-03")
    assert build_filename(meta) == "2026-10-03_Telekom_Rechnung September"
    assert safe_filename('a<b>:c?*"d') == "a b c d"
    assert safe_filename("...") == "Dokument"


def test_text_quality():
    assert text_quality("Sehr geehrter Herr Mustermann, anbei Ihre Rechnung") > 0.8
    assert text_quality("~~ |1 ;; 3x Q") < 0.3


def test_ocr_adds_searchable_layer_and_detects_blank():
    doc = pymupdf.open()
    scanned_page(doc, LETTER)
    scanned_page(doc, "")
    page, blank = doc[0], doc[1]
    assert page.get_text().strip() == ""
    r = process_page(page)
    assert r.ocr_used and "Jahresabrechnung" in r.text
    assert "Jahresabrechnung" in page.get_text()  # Textebene ist eingebettet
    assert process_page(blank).blank


def test_ocr_fixes_upside_down_page():
    doc = pymupdf.open()
    page = scanned_page(doc, LETTER, rotate=180)
    r = process_page(page)
    assert r.rotated_by == 180
    assert "Jahresabrechnung" in r.text


def test_pipeline_end_to_end_with_fake_model(tmp_path, monkeypatch):
    s = Settings(input_dir=str(tmp_path / "in"), output_dir=str(tmp_path / "out"),
                 archive_dir=str(tmp_path / "arch"), error_dir=str(tmp_path / "err"),
                 review_mode="pruefen")
    s.ensure_dirs()
    doc = pymupdf.open()
    scanned_page(doc, LETTER + "\nSeite 1 von 2")
    scanned_page(doc, "Verbrauchsübersicht Strom und Gas\nSeite 2 von 2")
    scanned_page(doc, "")
    scanned_page(doc, "Autohaus Schmidt\nRechnung über Inspektion Ihres Fahrzeugs VW Golf")
    doc.save(tmp_path / "in" / "stapel.pdf")

    p = Pipeline(s, Taxonomy())
    monkeypatch.setattr(p.client, "check", lambda: None)
    answers = [
        {"titel": "Jahresabrechnung 2026", "dokumenttyp": "Rechnung", "korrespondent": "Stadtwerke München",
         "datum": "2026-01-15", "bereich": "Privat", "hauptthema": "Energie", "weiteres_thema": "keines",
         "sicherheit": 90},
        {"titel": "Inspektion", "dokumenttyp": "Rechnung", "korrespondent": "Autohaus Schmidt",
         "datum": "", "bereich": "Privat", "hauptthema": "Auto", "weiteres_thema": "keines", "sicherheit": 80},
    ]
    monkeypatch.setattr(p.client, "chat_json", lambda *a: answers.pop(0))
    p._seen = {}
    files = list((tmp_path / "in").glob("*.pdf"))
    for f in files:
        p.process_file(f)

    out = sorted(x.name for x in (tmp_path / "out").glob("*.pdf"))
    review = sorted(x.name for x in (tmp_path / "out" / "_Pruefen").glob("*.pdf"))
    # Seite 4 nach „Seite 2 von 2“ ist per Regel sicher neu → nichts zur Prüfung
    assert out == ["2026-01-15_Stadtwerke München_Jahresabrechnung 2026.pdf", "Autohaus Schmidt_Inspektion.pdf"]
    assert review == []
    assert list((tmp_path / "arch").glob("*.pdf"))
    with pymupdf.open(tmp_path / "out" / out[0]) as d:
        assert d.page_count == 2
        assert d.metadata["keywords"] == "Privat, Energie"
