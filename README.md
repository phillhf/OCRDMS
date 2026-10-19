# OCRDMS

Web-App für Windows, die eingescannte Papierstapel automatisch in einzelne, durchsuchbare und verschlagwortete PDF-Dokumente verwandelt – bedienbar im Browser von PC, Tablet und Handy.

1. **Erfassen** – Eingangsordner (z. B. Scanner-Ziel), Upload per Drag & Drop oder **Scannen mit der Handy-Kamera** direkt im Browser (Blattkanten werden erkannt, das Bild begradigt und aufgehellt).
2. **OCR** – jede Seite bekommt eine unsichtbare, durchsuchbare Textebene (Tesseract, in PyMuPDF eingebaut; deutsche Sprachdaten werden mitgeliefert).
3. **Aufräumen** – leere Rückseiten (Duplex-Scan) werden entfernt, auf dem Kopf liegende Seiten gedreht.
4. **Trennen** – ein Stapel wird in einzelne Dokumente aufgeteilt: zuerst über Regeln („Seite 1 von 3“), sonst entscheidet ein lokales Sprachmodell über [Ollama](https://ollama.com). Dateien im Unterordner `Eingang\Einzeldokument` werden nicht getrennt.
5. **Verschlagworten** – Titel, Dokumenttyp, Korrespondent, Datum und Tags; Tags und Typen ausschließlich aus einer festen, in der Weboberfläche pflegbaren Liste.
6. **Ablage** – jedes Dokument als eigene PDF (Metadaten eingebettet) plus JSON-Datei im Ordner *Verarbeitet*; das Original wandert nach *Originale*.

Geplant: direkter Upload nach [Paperless-ngx](https://docs.paperless-ngx.com/), Prüfansicht für unsichere Trennungen.

## Installation

`OCRDMS-Setup-x.y.z.exe` ausführen. Der Installer fragt nach

- **Port** der Weboberfläche (Standard 8443),
- **Arbeitsordner** (Standard `C:\OCRDMS` mit Eingang/Verarbeitet/Originale/Fehler),
- **Betriebsart**: Windows-Dienst (läuft immer) oder Programm im Infobereich (startet bei Anmeldung),
- **HTTPS** und **Firewall** (Zugriff nur aus dem lokalen Netz).

Danach im Browser `https://<Servername>:<Port>` öffnen und beim ersten Aufruf ein Passwort festlegen. Voraussetzung ist ein erreichbares Ollama mit einem Modell (Standard `qwen3.5:4b`); Adresse und Modell lassen sich in den Einstellungen ändern.

### Updates

OCRDMS prüft regelmäßig die [GitHub-Releases](https://github.com/phillhf/OCRDMS/releases) und zeigt neue Versionen in der Übersicht an. Ein Klick auf *Jetzt aktualisieren* lädt den Installer, prüft dessen SHA-256-Prüfsumme und installiert ihn still – Port, Ordner, Betriebsart und Firewall-Einstellungen bleiben erhalten, OCRDMS startet danach neu.

Solange das Repository privat ist, braucht OCRDMS dafür einen GitHub-Token mit Leserecht (*Einstellungen → Updates*): auf GitHub unter *Settings → Developer settings → Fine-grained tokens* einen Token anlegen, nur für das Repository `OCRDMS`, Berechtigung *Contents: Read-only*.

### HTTPS

HTTPS nutzt eine eigene lokale Zertifizierungsstelle. Wer deren Stammzertifikat (Download unter *Einstellungen → Netzwerk*) einmal auf Handy/PC installiert, bekommt keine Zertifikatswarnung mehr.

## Entwicklung

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m ocrdms serve --port 18080 --http   # Server im Vordergrund
.venv\Scripts\python -m ocrdms once                        # Eingang einmal ohne Server verarbeiten
.venv\Scripts\python -m pytest                             # Tests (ohne Ollama)
.venv\Scripts\python tests\make_samples.py C:\Pfad\zum\Eingang   # Test-Scanstapel erzeugen
```

Mit der Umgebungsvariable `OCRDMS_DATA` lässt sich ein eigener Datenordner verwenden (Standard: `%PROGRAMDATA%\OCRDMS` für Einstellungen, Passwort-Hash, Zertifikate und Protokolle).

### Installer bauen und veröffentlichen

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # → dist\OCRDMS-Setup-<Version>.exe
```

Release: Version in `src\ocrdms\__init__.py` erhöhen, committen und einen passenden Tag pushen (`git tag v0.3.1` und `git push origin v0.3.1`). GitHub Actions testet, baut den Installer und veröffentlicht ihn als Release – installierte Instanzen finden das Update dann automatisch.

## Lizenz

AGPL-3.0-or-later (wegen PyMuPDF). Tesseract-Sprachdaten: Apache-2.0.
