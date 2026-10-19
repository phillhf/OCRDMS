"""Einstellungen und Tag-Liste, gespeichert als JSON unter %APPDATA%\\OCRDMS."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .paths import app_data_dir, default_work_dir

log = logging.getLogger(__name__)

DEFAULT_DOCUMENT_TYPES = [
    "Rechnung", "Angebot", "Auftragsbestätigung", "Lieferschein", "Gutschrift", "Mahnung",
    "Quittung", "Vertrag", "Kündigung", "Bescheid", "Kontoauszug", "Gehaltsabrechnung",
    "Versicherungsschein", "Bescheinigung", "Zeugnis", "Brief", "Formular", "Sonstiges",
]

DEFAULT_TAGS = [
    "Privat", "Geschäftlich", "Steuer", "Finanzen", "Bank", "Versicherung", "Gesundheit",
    "Wohnung", "Auto", "Telekommunikation", "Energie", "Behörde", "Arbeit", "Personal",
    "Einkauf", "Verkauf", "Recht", "Bildung", "Familie", "Garantie",
]

# Bereichs-Tags: genau einer davon wird je Dokument vergeben (wenn in der Tag-Liste vorhanden)
SCOPE_TAGS = ("Privat", "Geschäftlich")

# Kurze Erklärungen helfen kleinen Modellen enorm bei der richtigen Zuordnung
DEFAULT_TAG_DESCRIPTIONS = {
    "Privat": "an eine Privatperson adressiert bzw. private Angelegenheit",
    "Geschäftlich": "an eine Firma adressiert bzw. betriebliche Angelegenheit",
    "Steuer": "Finanzamt, Steuerbescheide, steuerlich relevante Nachweise",
    "Finanzen": "Kredite, Geldanlage, Zahlungen, Darlehen",
    "Bank": "Kontoauszüge und Schreiben von Banken/Sparkassen",
    "Versicherung": "Versicherungsscheine, Beiträge, Schadensfälle",
    "Gesundheit": "Arzt, Krankenkasse, Krankenhaus, Apotheke, Pflege",
    "Wohnung": "Miete, Nebenkosten, Hausverwaltung, Immobilie",
    "Auto": "Fahrzeug, Werkstatt, Zulassung, Kfz-Versicherung, Kfz-Steuer",
    "Telekommunikation": "Telefon, Handy, Internet, Fernsehen",
    "Energie": "nur Strom, Gas, Heizöl, Fernwärme, Wasser – nicht Telefon/Internet, nicht Kraftstoff",
    "Behörde": "Ämter, Stadt, Gemeinde, Rentenversicherung, Agentur für Arbeit",
    "Arbeit": "eigener Arbeitgeber, Arbeitsvertrag, Gehalt",
    "Personal": "Unterlagen zu Mitarbeitern des eigenen Betriebs",
    "Einkauf": "Bestellungen und Käufe, Rechnungen von Lieferanten",
    "Verkauf": "eigene Ausgangsrechnungen und Aufträge an Kunden",
    "Recht": "Anwalt, Gericht, rechtliche Auseinandersetzungen",
    "Bildung": "Schule, Studium, Kurse, Weiterbildung",
    "Familie": "Kinder, Kindergeld, Ehe, Familienangelegenheiten",
    "Garantie": "Kaufbelege mit Garantie oder Gewährleistung",
}


def _dir(name: str) -> str:
    return str(default_work_dir() / name)


@dataclass
class Settings:
    input_dir: str = field(default_factory=lambda: _dir("Eingang"))
    output_dir: str = field(default_factory=lambda: _dir("Verarbeitet"))
    archive_dir: str = field(default_factory=lambda: _dir("Originale"))
    error_dir: str = field(default_factory=lambda: _dir("Fehler"))
    interval_minutes: int = 5
    auto_run: bool = True

    ollama_url: str = "http://localhost:11434"
    model: str = "qwen3.5:4b"
    llm_timeout_s: int = 600

    ocr_dpi: int = 300
    ocr_language: str = "deu"
    remove_blank_pages: bool = True
    blank_ink_ratio: float = 0.004  # Anteil dunkler Pixel, unter dem eine Seite als leer gilt

    # "auto": alles direkt ablegen; "pruefen": unsichere Trennungen zur Prüfung markieren
    review_mode: str = "auto"
    review_confidence: int = 70

    def dirs(self) -> list[Path]:
        return [Path(p) for p in (self.input_dir, self.output_dir, self.archive_dir, self.error_dir)]

    def ensure_dirs(self) -> None:
        for d in self.dirs():
            d.mkdir(parents=True, exist_ok=True)


@dataclass
class Taxonomy:
    tags: list[str] = field(default_factory=lambda: list(DEFAULT_TAGS))
    document_types: list[str] = field(default_factory=lambda: list(DEFAULT_DOCUMENT_TYPES))
    tag_descriptions: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TAG_DESCRIPTIONS))

    def scope_tags(self) -> list[str]:
        return [t for t in SCOPE_TAGS if t in self.tags]

    def topic_tags(self) -> list[str]:
        return [t for t in self.tags if t not in SCOPE_TAGS]


@dataclass
class ServerConfig:
    """Netzwerk-Einstellungen (server.json) – wird vom Installer geschrieben, Änderung erfordert Neustart."""
    port: int = 8443
    host: str = "0.0.0.0"
    https: bool = True


def _load(cls, path: Path):
    if not path.exists():
        return cls()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
    except Exception:
        log.exception("Konnte %s nicht lesen – verwende Standardwerte", path)
        return cls()


def _save(obj, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(obj), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def taxonomy_path() -> Path:
    return app_data_dir() / "taxonomy.json"


def load_settings() -> Settings:
    return _load(Settings, settings_path())


def save_settings(s: Settings) -> None:
    _save(s, settings_path())


def load_taxonomy() -> Taxonomy:
    return _load(Taxonomy, taxonomy_path())


def save_taxonomy(t: Taxonomy) -> None:
    _save(t, taxonomy_path())


def server_config_path() -> Path:
    return app_data_dir() / "server.json"


def load_server_config() -> ServerConfig:
    return _load(ServerConfig, server_config_path())


def save_server_config(c: ServerConfig) -> None:
    _save(c, server_config_path())
