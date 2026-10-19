"""Einfaches Login für einen Benutzer: Passwort-Hash (scrypt) und Sitzungsschlüssel unter %PROGRAMDATA%."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path

from .paths import app_data_dir

MIN_PASSWORD_LENGTH = 8


def _auth_path() -> Path:
    return app_data_dir() / "auth.json"


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


def password_is_set() -> bool:
    return _auth_path().exists()


def set_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
    salt = secrets.token_bytes(16)
    data = {"salt": salt.hex(), "hash": _hash(password, salt).hex()}
    tmp = _auth_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(_auth_path())


def check_password(password: str) -> bool:
    try:
        data = json.loads(_auth_path().read_text())
    except (OSError, ValueError):
        return False
    return hmac.compare_digest(_hash(password, bytes.fromhex(data["salt"])), bytes.fromhex(data["hash"]))


def session_secret() -> str:
    path = app_data_dir() / "session.key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48))
    return path.read_text().strip()
