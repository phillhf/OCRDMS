"""Tests der Web-API und der Scan-Aufbereitung (ohne Ollama, ohne echtes Netzwerk)."""

import io

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OCRDMS_DATA", str(tmp_path / "data"))
    monkeypatch.setattr("ocrdms.config.default_work_dir", lambda: tmp_path / "work")
    from ocrdms.config import ServerConfig
    from ocrdms.engine import Engine
    from ocrdms.web import create_app

    engine = Engine()
    engine.run_now = lambda: True  # keine echte Verarbeitung im Test
    app = create_app(engine, ServerConfig(port=1, https=False))
    with TestClient(app) as c:
        c.engine = engine
        yield c
    engine.stop()


def login(c):
    r = c.post("/api/auth/setup", json={"password": "geheim123"})
    assert r.status_code == 200, r.text


def test_auth_flow(client):
    assert client.get("/api/auth").json()["setup_required"] is True
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/auth/setup", json={"password": "kurz"}).status_code == 400
    login(client)
    assert client.get("/api/status").status_code == 200
    assert client.post("/api/auth/setup", json={"password": "nochmal123"}).status_code == 409
    client.post("/api/auth/logout")
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/auth/login", json={"password": "falsch"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "geheim123"}).status_code == 200


def test_index_and_static(client):
    assert "OCRDMS" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_settings_roundtrip_and_validation(client, tmp_path):
    login(client)
    s = client.get("/api/settings").json()
    s["interval_minutes"] = 9999
    r = client.put("/api/settings", json=s)
    assert r.status_code == 200 and r.json()["interval_minutes"] == 1440
    s["output_dir"] = s["input_dir"]
    assert client.put("/api/settings", json=s).status_code == 400


def test_server_config_port(client):
    login(client)
    assert client.put("/api/server", json={"port": 70000}).status_code == 400
    r = client.put("/api/server", json={"port": 9443, "https": True})
    assert r.json()["restart_needed"] is True
    assert client.get("/api/server").json()["port"] == 9443


def test_taxonomy(client):
    login(client)
    r = client.put("/api/taxonomy", json={"tags": ["Privat", "Auto", "Auto", " "], "document_types": ["Rechnung"],
                                          "tag_descriptions": {"Auto": "Fahrzeug", "Fremd": "x"}})
    assert r.json() == {"tags": ["Privat", "Auto"], "document_types": ["Rechnung"], "tag_descriptions": {"Auto": "Fahrzeug"}}
    assert client.put("/api/taxonomy", json={"tags": [], "document_types": ["x"]}).status_code == 400


def _pdf_bytes():
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "Hallo")
    return d.tobytes()


def test_upload_pdf_and_images(client, tmp_path):
    login(client)
    r = client.post("/api/upload", files=[("files", ("stapel.pdf", _pdf_bytes(), "application/pdf"))])
    assert r.status_code == 200
    assert (tmp_path / "work" / "Eingang" / "stapel.pdf").exists()
    img = cv2.imencode(".png", np.full((200, 140, 3), 255, np.uint8))[1].tobytes()
    r = client.post("/api/upload", data={"single": "true"},
                    files=[("files", ("a.png", img, "image/png")), ("files", ("b.png", img, "image/png"))])
    saved = r.json()["saved"]
    path = tmp_path / "work" / "Eingang" / "Einzeldokument" / saved[0]
    with pymupdf.open(path) as d:
        assert d.page_count == 2
    assert client.post("/api/upload", files=[("files", ("x.exe", b"MZ", "application/octet-stream"))]).status_code == 400


def _photo_of_paper() -> bytes:
    """Simuliertes Handyfoto: helles, schräg liegendes Blatt mit Text auf dunklem Tisch."""
    img = np.full((1200, 900, 3), (60, 50, 45), np.uint8)
    paper = np.array([[180, 150], [760, 210], [700, 1080], [130, 1010]], np.int32)
    cv2.fillPoly(img, [paper], (235, 235, 230))
    for i in range(12):
        cv2.putText(img, "Rechnung Zeile %d" % i, (220, 300 + i * 55), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 30, 30), 2)
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_document_detection():
    from ocrdms.scan import decode_image, find_document
    corners = find_document(decode_image(_photo_of_paper()))
    assert corners is not None
    tl = corners[0]
    assert abs(tl[0] - 180) < 25 and abs(tl[1] - 150) < 25


def test_scan_session_flow(client, tmp_path):
    login(client)
    sid = client.post("/api/scan").json()["id"]
    p1 = client.post(f"/api/scan/{sid}/photo", files={"file": ("f.jpg", _photo_of_paper(), "image/jpeg")},
                     data={"mode": "auto"}).json()
    assert p1["detected"] is True
    p2 = client.post(f"/api/scan/{sid}/photo", files={"file": ("f.jpg", _photo_of_paper(), "image/jpeg")},
                     data={"mode": "sw"}).json()
    assert client.get(p1["thumb"]).headers["content-type"] == "image/jpeg"
    assert client.post(f"/api/scan/{sid}/page/{p2['id']}/rotate?cw=true").status_code == 200
    assert client.post(f"/api/scan/{sid}/page/{p1['id']}/mode", json={"mode": "farbe"}).status_code == 200
    assert client.post(f"/api/scan/{sid}/order", json={"order": [p2["id"], p1["id"]]}).status_code == 200
    r = client.post(f"/api/scan/{sid}/finish", json={"single": True, "name": "Testscan"})
    assert r.json()["saved"] == "Testscan.pdf"
    with pymupdf.open(tmp_path / "work" / "Eingang" / "Einzeldokument" / "Testscan.pdf") as d:
        assert d.page_count == 2
        assert d[0].rect.width > d[0].rect.height  # gedrehte Seite steht jetzt vorne im Querformat
    assert client.get(f"/api/scan/{sid}").status_code == 404


def test_documents_and_file_access(client, tmp_path):
    login(client)
    out = tmp_path / "work" / "Verarbeitet"
    (out / "doc.pdf").write_bytes(_pdf_bytes())
    (out / "doc.json").write_text('{"datei": "doc.pdf", "metadaten": {}, "seiten_im_original": [1]}', encoding="utf-8")
    docs = client.get("/api/documents").json()
    assert docs[0]["pfad"] == "doc.pdf"
    assert client.get("/api/files/pdf", params={"path": "doc.pdf"}).status_code == 200
    assert client.get("/api/files/thumb", params={"path": "doc.pdf"}).headers["content-type"] == "image/png"
    assert client.get("/api/files/pdf", params={"path": "../data/auth.json"}).status_code == 404


def test_certificates(tmp_path, monkeypatch):
    monkeypatch.setenv("OCRDMS_DATA", str(tmp_path / "data"))
    from cryptography import x509

    from ocrdms.certs import ca_cert_path, ensure_server_cert
    crt, key = ensure_server_cert()
    cert = x509.load_pem_x509_certificate(crt.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert ca_cert_path().exists()
    mtime = crt.stat().st_mtime_ns
    ensure_server_cert()
    assert crt.stat().st_mtime_ns == mtime  # unverändert → nicht neu ausgestellt


def test_settings_never_expose_github_token(client):
    login(client)
    r = client.put("/api/settings", json={"github_token": "geheimer-token", "github_repo": "me/OCRDMS"})
    assert r.status_code == 200
    body = client.get("/api/settings").json()
    assert "github_token" not in body and body["github_token_set"] is True
    assert client.engine.settings.github_token == "geheimer-token"
    client.put("/api/settings", json={"github_token": ""})  # leer = unverändert
    assert client.engine.settings.github_token == "geheimer-token"
    client.put("/api/settings", json={"github_token_clear": True})
    assert client.engine.settings.github_token == ""
    assert client.put("/api/settings", json={"github_repo": "kein repo"}).status_code == 400
