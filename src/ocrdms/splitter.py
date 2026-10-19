"""Dokumentgrenzen in einem Seitenstapel finden: erst feste Regeln, dann das Sprachmodell."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from .ollama_client import OllamaClient

log = logging.getLogger(__name__)

_PAGE_MARK = re.compile(
    r"\b(?:Seite|Blatt|Page)\s*:?\s*(\d{1,3})\s*(?:von|/|of|aus)\s*(\d{1,3})\b", re.IGNORECASE
)


@dataclass
class Boundary:
    """Entscheidung für den Übergang vor einer Seite."""
    page: int  # Index der Seite, vor der entschieden wird
    new_document: bool
    confidence: int  # 0–100
    source: str  # "regel" | "modell" | "standard"
    reason: str = ""


@dataclass
class DocumentGroup:
    pages: list[int] = field(default_factory=list)
    boundary: Boundary | None = None  # Entscheidung, die dieses Dokument begonnen hat
    uncertain_links: list[Boundary] = field(default_factory=list)  # unsichere "gehört dazu"-Entscheidungen


def page_marker(text: str) -> tuple[int, int] | None:
    """Findet „Seite x von y“. Bei mehreren Treffern zählt der plausibelste (x ≤ y)."""
    for m in _PAGE_MARK.finditer(text):
        x, y = int(m.group(1)), int(m.group(2))
        if 1 <= x <= y <= 200:
            return x, y
    return None


def rule_boundary(prev_text: str, cur_text: str) -> tuple[bool, int, str] | None:
    cur, prev = page_marker(cur_text), page_marker(prev_text)
    if cur:
        x, y = cur
        if x == 1:
            return True, 95, f"Seite 1 von {y}"
        if prev and prev[1] == y and prev[0] == x - 1:
            return False, 99, f"Seitenfolge {prev[0]}→{x} von {y}"
        return False, 85, f"Seite {x} von {y}"
    if prev and prev[0] == prev[1]:
        return True, 85, f"vorherige Seite war letzte ({prev[0]} von {prev[1]})"
    return None


SYSTEM_PROMPT = (
    "Du bist ein Assistent für die Dokumentenverarbeitung. Ein Stapel eingescannter Papierseiten "
    "enthält mehrere unterschiedliche Dokumente hintereinander (Briefe, Rechnungen, Verträge, Bescheide …). "
    "Deine Aufgabe: entscheiden, ob eine Seite ein NEUES Dokument beginnt oder die Fortsetzung des "
    "vorherigen Dokuments ist. Hinweise auf ein neues Dokument: neuer Briefkopf/Absender, Empfängeradresse, "
    "neues Datum, neuer Betreff, Anrede wie „Sehr geehrte“, Titelzeile, anderer Dokumenttyp. "
    "Hinweise auf eine Fortsetzung: Satz läuft weiter, gleiche Positionen/Tabelle, Seitenzahl > 1, "
    "Grußformel/Unterschrift ohne neuen Kopf, AGB oder Anlagen desselben Absenders. "
    "Gib bei 'sicherheit' an, wie sicher du dir bist (0 = geraten, 100 = eindeutig). "
    "Die 'begruendung' ist ein kurzer Stichpunkt mit höchstens 10 Wörtern."
)

BOUNDARY_SCHEMA = {
    "type": "object",
    "properties": {
        "neues_dokument": {"type": "boolean"},
        "sicherheit": {"type": "integer", "minimum": 0, "maximum": 100},
        "begruendung": {"type": "string"},
    },
    "required": ["neues_dokument", "sicherheit", "begruendung"],
}


def _clip(text: str, n: int, tail: bool = False) -> str:
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= n:
        return text
    return "…" + text[-n:] if tail else text[:n] + "…"


def llm_boundary(client: OllamaClient, doc_start_text: str | None, prev_text: str, cur_text: str) -> tuple[bool, int, str]:
    start = ""
    if doc_start_text is not None:  # nur wenn das aktuelle Dokument schon mehr als eine Seite hat
        start = f"### Anfang des aktuellen Dokuments (erste Seite, Auszug)\n{_clip(doc_start_text, 600)}\n\n"
    user = (
        f"{start}"
        "### Ende der vorherigen Seite\n"
        f"{_clip(prev_text, 700, tail=True)}\n\n"
        "### Anfang der neuen Seite\n"
        f"{_clip(cur_text, 1400)}\n\n"
        "Beginnt die neue Seite ein neues Dokument? Antworte als JSON."
    )
    r = client.chat_json(SYSTEM_PROMPT, user, BOUNDARY_SCHEMA)
    conf = max(0, min(100, int(r.get("sicherheit", 50))))
    return bool(r.get("neues_dokument")), conf, str(r.get("begruendung", ""))[:300]


def split_pages(
    texts: dict[int, str],
    client: OllamaClient | None,
    review_confidence: int = 70,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> list[DocumentGroup]:
    """Teilt die (nicht leeren) Seiten in Dokumente auf. `texts`: Seitenindex → Text, in Reihenfolge."""
    order = list(texts)
    groups: list[DocumentGroup] = []
    for n, idx in enumerate(order):
        if cancelled():
            raise InterruptedError
        if progress:
            progress(n + 1, len(order))
        if not groups:
            groups.append(DocumentGroup(pages=[idx], boundary=Boundary(idx, True, 100, "standard", "erste Seite")))
            continue

        cur = groups[-1]
        prev_text, cur_text = texts[cur.pages[-1]], texts[idx]
        decision = rule_boundary(prev_text, cur_text)
        if decision:
            b = Boundary(idx, decision[0], decision[1], "regel", decision[2])
        elif len(cur_text.strip()) < 30:
            b = Boundary(idx, False, 40, "standard", "kaum Text – vermutlich Anlage/Rückseite")
        elif client is None:
            b = Boundary(idx, False, 0, "standard", "kein Sprachmodell")
        else:
            doc_start = texts[cur.pages[0]] if len(cur.pages) > 1 else None
            new, conf, reason = llm_boundary(client, doc_start, prev_text, cur_text)
            b = Boundary(idx, new, conf, "modell", reason)
        log.info("Seite %d: %s (%d%%, %s) %s", idx + 1, "NEU" if b.new_document else "gehört dazu",
                 b.confidence, b.source, b.reason)

        if b.new_document:
            groups.append(DocumentGroup(pages=[idx], boundary=b))
        else:
            cur.pages.append(idx)
            if b.confidence < review_confidence:
                cur.uncertain_links.append(b)
    return groups


def group_is_uncertain(g: DocumentGroup, review_confidence: int) -> bool:
    return bool(g.uncertain_links) or (g.boundary is not None and g.boundary.confidence < review_confidence)
