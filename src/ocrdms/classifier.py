"""Metadaten für ein Dokument per Sprachmodell bestimmen – Tags und Typen nur aus der festen Liste."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from .config import Taxonomy
from .ollama_client import OllamaClient

NO_TOPIC = "keines"
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

SYSTEM_PROMPT = (
    "Du bist ein Assistent für ein Dokumentenmanagementsystem. Du erhältst den OCR-Text eines "
    "eingescannten Dokuments und bestimmst seine Metadaten:\n"
    "- titel: kurzer, aussagekräftiger Titel auf Deutsch (max. 50 Zeichen), z. B. „Stromrechnung September 2026“. "
    "Den Absender NICHT in den Titel schreiben.\n"
    "- dokumenttyp: genau einer aus der vorgegebenen Liste.\n"
    "- korrespondent: kurzer Name der Firma, Behörde oder Person, von der das Dokument stammt "
    "(z. B. „Telekom“ statt „Telekom Deutschland GmbH“). Bei Verträgen der Vertragspartner. Leer, wenn nicht erkennbar.\n"
    "- datum: Ausstellungsdatum des Dokuments im Format JJJJ-MM-TT, leer wenn nicht erkennbar.\n"
    "{bereich}"
    "- hauptthema: das EINE Thema aus der Themenliste, das am besten passt.\n"
    "- weiteres_thema: nur wenn ein zweites Thema ganz eindeutig ebenfalls zutrifft, sonst „keines“.\n"
    "- sicherheit: wie sicher die Einordnung ist (0–100)."
)

BEREICH_PROMPT = (
    "- bereich: „{a}“ oder „{b}“. Ist das Dokument an eine Privatperson (Herr/Frau …) adressiert "
    "oder betrifft private Angelegenheiten, dann „{a}“; ist es an eine Firma adressiert, dann „{b}“.\n"
)


@dataclass
class DocumentMeta:
    titel: str = "Unbekanntes Dokument"
    dokumenttyp: str = "Sonstiges"
    korrespondent: str = ""
    datum: str = ""
    tags: list[str] = field(default_factory=list)
    sicherheit: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def build_schema(tax: Taxonomy) -> dict:
    props = {
        "titel": {"type": "string"},
        "dokumenttyp": {"type": "string", "enum": tax.document_types},
        "korrespondent": {"type": "string"},
        "datum": {"type": "string"},
    }
    if len(tax.scope_tags()) == 2:
        props["bereich"] = {"type": "string", "enum": tax.scope_tags()}
    if tax.topic_tags():
        props["hauptthema"] = {"type": "string", "enum": tax.topic_tags()}
        props["weiteres_thema"] = {"type": "string", "enum": [NO_TOPIC] + tax.topic_tags()}
    props["sicherheit"] = {"type": "integer", "minimum": 0, "maximum": 100}
    return {"type": "object", "properties": props, "required": list(props)}


def build_system_prompt(tax: Taxonomy) -> str:
    scopes = tax.scope_tags()
    bereich = BEREICH_PROMPT.format(a=scopes[0], b=scopes[1]) if len(scopes) == 2 else ""
    return SYSTEM_PROMPT.format(bereich=bereich)


def describe_tags(tax: Taxonomy) -> str:
    lines = []
    for t in tax.topic_tags():
        desc = tax.tag_descriptions.get(t, "").strip()
        lines.append(f"- {t}: {desc}" if desc else f"- {t}")
    return "\n".join(lines)


def document_excerpt(page_texts: list[str], limit: int = 3500) -> str:
    """Anfang des Dokuments (wichtigste Infos) plus ggf. etwas vom Ende."""
    full = "\n\n--- Seitenumbruch ---\n\n".join(t.strip() for t in page_texts)
    full = re.sub(r"[ \t]+", " ", full)
    if len(full) <= limit:
        return full
    head = int(limit * 0.8)
    return full[:head] + "\n\n[…]\n\n" + full[-(limit - head):]


def _clean_date(value: str) -> str:
    m = _DATE_RE.match(value.strip())
    if not m:
        return ""
    try:
        d = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return ""
    today = date.today()
    if d.year < 1950 or d.year > today.year + 1:
        return ""
    return d.isoformat()


def validate(raw: dict, tax: Taxonomy) -> DocumentMeta:
    tags = []
    bereich = raw.get("bereich")
    if bereich in tax.scope_tags():
        tags.append(bereich)
    for t in (raw.get("hauptthema"), raw.get("weiteres_thema")):
        if t in tax.topic_tags() and t not in tags:
            tags.append(t)
    doc_type = raw.get("dokumenttyp")
    if doc_type not in tax.document_types:
        doc_type = "Sonstiges" if "Sonstiges" in tax.document_types else (tax.document_types or [""])[0]
    try:
        conf = int(raw.get("sicherheit") or 0)
    except (TypeError, ValueError):
        conf = 0
    return DocumentMeta(
        titel=(str(raw.get("titel") or "").strip() or "Unbekanntes Dokument")[:80],
        dokumenttyp=doc_type,
        korrespondent=str(raw.get("korrespondent") or "").strip()[:60],
        datum=_clean_date(str(raw.get("datum") or "")),
        tags=tags,
        sicherheit=max(0, min(100, conf)),
    )


def classify(client: OllamaClient, page_texts: list[str], tax: Taxonomy) -> DocumentMeta:
    user = (
        f"Erlaubte Dokumenttypen: {', '.join(tax.document_types)}\n\n"
        f"Themenliste:\n{describe_tags(tax)}\n\n"
        f"### Dokumenttext\n{document_excerpt(page_texts)}\n\n"
        "Bestimme die Metadaten und antworte als JSON."
    )
    raw = client.chat_json(build_system_prompt(tax), user, build_schema(tax))
    return validate(raw, tax)
