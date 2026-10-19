"""Erzeugt künstliche „Scan-Stapel“ (reine Bild-PDFs) zum Testen der Verarbeitung.

Aufruf: python tests/make_samples.py <Zielordner>
"""

import sys
from pathlib import Path

import pymupdf

LOREM = (
    "Wir bedanken uns für Ihr Vertrauen. Bei Rückfragen erreichen Sie uns montags bis freitags "
    "von 8 bis 18 Uhr unter der oben genannten Telefonnummer. "
)

DOCS = [
    # (Seiten, Seitenzahlen anzeigen)
    ([
        "Telekom Deutschland GmbH · Landgrabenweg 151 · 53227 Bonn\n\nHerrn\nMax Mustermann\nHauptstraße 5\n80331 München\n\n"
        "Bonn, 03.10.2026\n\nIhre Rechnung für September 2026\nKundennummer 123456789  Rechnungsnummer 2026-0915-4711\n\n"
        "Sehr geehrter Herr Mustermann,\n\nhiermit erhalten Sie Ihre Rechnung für Ihren Festnetz- und Internetanschluss.\n\n"
        "MagentaZuhause L          01.09.–30.09.2026      44,95 EUR\nMagentaTV Smart           01.09.–30.09.2026      10,00 EUR\n"
        "Verbindungen national                            2,31 EUR\n\nSumme netto 48,85 EUR\nUmsatzsteuer 19 % 9,28 EUR\n" + LOREM,
        "Rechnungsbetrag brutto 58,13 EUR\n\nDer Betrag wird am 15.10.2026 von Ihrem Konto DE12 3456 7890 1234 5678 90 abgebucht.\n\n"
        "Einzelverbindungsnachweis siehe Anlage. " + LOREM * 3 + "\n\nMit freundlichen Grüßen\nIhre Telekom",
    ], True),
    ([
        "AOK Bayern – Die Gesundheitskasse\nDirektion München · Landsberger Str. 150 · 80339 München\n\n"
        "Herrn\nMax Mustermann\nHauptstraße 5\n80331 München\n\nMünchen, 28.08.2026\n\n"
        "Mitgliedsbescheinigung\n\nSehr geehrter Herr Mustermann,\n\nhiermit bestätigen wir, dass Sie seit dem 01.01.2019 "
        "bei der AOK Bayern als Pflichtmitglied krankenversichert sind. Die Versicherung besteht ununterbrochen fort.\n"
        "Versichertennummer: A123456789\n\nDiese Bescheinigung wurde maschinell erstellt und ist ohne Unterschrift gültig.\n\n"
        "Mit freundlichen Grüßen\nIhre AOK Bayern",
    ], False),
    (None, False),  # leere Rückseite
    ([
        "MIETVERTRAG FÜR WOHNRAUM\n\nZwischen\nFrau Erika Vermieter, Lindenweg 3, 81245 München (Vermieterin)\nund\n"
        "Herrn Max Mustermann, derzeit wohnhaft Hauptstraße 5, 80331 München (Mieter)\n\nwird folgender Mietvertrag geschlossen:\n\n"
        "§ 1 Mietsache\nVermietet wird die Wohnung im 2. Obergeschoss des Hauses Lindenweg 3, 81245 München, bestehend aus "
        "3 Zimmern, Küche, Bad, Flur und Balkon. Die Wohnfläche beträgt ca. 78 m².\n\n§ 2 Mietzeit\nDas Mietverhältnis beginnt "
        "am 01.11.2026 und läuft auf unbestimmte Zeit.\n\n§ 3 Miete und Nebenkosten\nDie monatliche Grundmiete beträgt "
        "1.150,00 EUR. Zusätzlich ist eine Vorauszahlung auf die Betriebskosten von 220,00 EUR zu leisten. Die Miete ist",
        "monatlich im Voraus, spätestens bis zum dritten Werktag des Monats, auf das Konto der Vermieterin zu zahlen.\n\n"
        "§ 4 Kaution\nDer Mieter leistet eine Mietsicherheit in Höhe von drei Nettokaltmieten (3.450,00 EUR).\n\n"
        "§ 5 Schönheitsreparaturen\nDie Schönheitsreparaturen trägt der Mieter nach Maßgabe der gesetzlichen Bestimmungen.\n\n"
        "§ 6 Tierhaltung\nDie Haltung von Kleintieren ist gestattet. Hunde und Katzen nur nach Zustimmung der Vermieterin.\n\n"
        "§ 7 Hausordnung\nDie beigefügte Hausordnung ist Bestandteil dieses Vertrages.",
        "§ 8 Sonstige Vereinbarungen\nDer Mieter erhält zwei Haus- und drei Wohnungsschlüssel.\n\n"
        "§ 9 Schlussbestimmungen\nÄnderungen und Ergänzungen dieses Vertrages bedürfen der Schriftform.\n\n\n"
        "München, den 20.09.2026\n\n\n_______________________          _______________________\nVermieterin                              Mieter",
    ], False),
    ([
        "Autohaus Schmidt GmbH · Kfz-Meisterbetrieb · Industriestraße 12 · 85737 Ismaning\n\nHerrn\nMax Mustermann\n"
        "Hauptstraße 5\n80331 München\n\nRechnung Nr. W-26-00873          Datum: 07.10.2026\nFahrzeug: VW Golf VIII  Kennzeichen M-MM 1234\n\n"
        "Pos  Leistung                              Menge   Betrag\n1    Inspektion nach Herstellervorgabe         1    189,00\n"
        "2    Motoröl 5W-30                           4,5 l     67,50\n3    Ölfilter                                   1     18,90\n"
        "4    Hauptuntersuchung (HU/AU)                  1    139,00\n\nNetto 414,40 EUR\nMwSt. 19 % 78,74 EUR\nGesamt 493,14 EUR\n\n"
        "Zahlbar sofort ohne Abzug. Vielen Dank für Ihren Auftrag!",
    ], False),
]


def render_text_page(text: str, footer: str | None) -> pymupdf.Pixmap:
    tmp = pymupdf.open()
    p = tmp.new_page(width=595, height=842)
    p.insert_textbox(pymupdf.Rect(60, 60, 540, 780), text, fontsize=10.5, fontname="helv")
    if footer:
        p.insert_text((260, 810), footer, fontsize=9)
    return p.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)


def build_stack(out_path: Path, rotate_upside_down: set[int] = frozenset({4})) -> int:
    out = pymupdf.open()
    page_no = 0
    for pages, numbered in DOCS:
        if pages is None:
            pages = [""]
        for i, text in enumerate(pages):
            footer = f"Seite {i + 1} von {len(pages)}" if numbered else None
            pix = render_text_page(text, footer)
            page = out.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=pix.tobytes("jpeg", jpg_quality=80),
                              rotate=180 if page_no in rotate_upside_down else 0)
            page_no += 1
    out.save(out_path, garbage=3, deflate=True)
    return page_no


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    target.mkdir(parents=True, exist_ok=True)
    n = build_stack(target / "Scan_Stapel_Test.pdf")
    print(f"{target / 'Scan_Stapel_Test.pdf'}: {n} Seiten")
