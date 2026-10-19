"""Tests der Update-Logik ohne echte Verbindung zu GitHub."""

import hashlib

import pytest

from ocrdms import updater as U


class FakeResponse:
    def __init__(self, status=200, json_data=None, content=b"", headers=None):
        self.status_code, self._json, self.content = status, json_data, content
        self.headers = headers or {"content-length": str(len(content))}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._json

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


SETUP = b"MZ fake installer" * 100


def release(tag="v9.9.9", digest=None):
    return {"tag_name": tag, "body": "Neu: alles", "published_at": "2026-10-19T10:00:00Z",
            "assets": [{"id": 42, "name": f"OCRDMS-Setup-{tag[1:]}.exe", "size": len(SETUP),
                        "digest": digest if digest is not None else "sha256:" + hashlib.sha256(SETUP).hexdigest()}]}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OCRDMS_DATA", str(tmp_path / "data"))


def test_version_compare():
    assert U.is_newer("0.10.0", "0.9.9")
    assert U.is_newer("v1.0.0", "0.9")
    assert not U.is_newer("0.2.0", "0.2.0")
    assert not U.is_newer("0.1.9", "0.2.0")


def test_check_finds_update_and_sends_token(monkeypatch):
    seen = {}

    def fake_get(url, headers, timeout):
        seen.update(headers)
        return FakeResponse(json_data=release())
    monkeypatch.setattr(U.requests, "get", fake_get)
    info = U.Updater(lambda: ("me/OCRDMS", "tok123")).check()
    assert info.available and info.latest == "9.9.9" and info.asset_id == 42
    assert seen["Authorization"] == "Bearer tok123"


def test_check_private_repo_without_token(monkeypatch):
    monkeypatch.setattr(U.requests, "get", lambda *a, **k: FakeResponse(404, {}))
    info = U.Updater(lambda: ("me/OCRDMS", "")).check()
    assert not info.available and "Token" in info.error


def test_check_same_version_not_available(monkeypatch):
    monkeypatch.setattr(U.requests, "get", lambda *a, **k: FakeResponse(json_data=release("v" + U.__version__)))
    assert not U.Updater(lambda: ("me/OCRDMS", "")).check().available


def test_download_verifies_digest(monkeypatch):
    up = U.Updater(lambda: ("me/OCRDMS", "t"))
    monkeypatch.setattr(U.requests, "get", lambda *a, **k: FakeResponse(content=SETUP))
    info = U.UpdateInfo(latest="9.9.9", available=True, asset_id=42, asset_name="OCRDMS-Setup-9.9.9.exe",
                        size=len(SETUP), digest="sha256:" + hashlib.sha256(SETUP).hexdigest())
    path = up._download(info, "me/OCRDMS", "t")
    assert path.read_bytes() == SETUP and up.progress == 100

    info.digest = "sha256:" + "0" * 64
    with pytest.raises(U.UpdateError, match="Prüfsumme"):
        up._download(info, "me/OCRDMS", "t")


def test_install_refuses_outside_frozen_build(monkeypatch):
    up = U.Updater(lambda: ("me/OCRDMS", "t"))

    def fake_get(url, headers, **k):
        if url.endswith("/releases/latest"):
            return FakeResponse(json_data=release())
        return FakeResponse(content=SETUP)
    monkeypatch.setattr(U.requests, "get", fake_get)
    up._install()  # synchron statt im Thread
    assert up.state == "error" and "installierten Version" in up.info.error


def test_check_due_only_once():
    up = U.Updater(lambda: ("me/OCRDMS", ""))
    assert up.check_due() is True
    assert up.check_due() is False
