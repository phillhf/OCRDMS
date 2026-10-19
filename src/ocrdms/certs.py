"""Eigene kleine Zertifizierungsstelle für HTTPS im internen Netz.

Es wird eine lokale CA erzeugt, die das Server-Zertifikat signiert. Wer die CA einmal auf seinem
Handy/PC als vertrauenswürdig installiert, bekommt keine Zertifikatswarnungen mehr – auch nicht,
wenn das Server-Zertifikat neu ausgestellt wird (z. B. nach Änderung von Name oder IP).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import logging
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .paths import sub_dir

log = logging.getLogger(__name__)


def cert_dir() -> Path:
    return sub_dir("certs")


def ca_cert_path() -> Path:
    return cert_dir() / "OCRDMS-CA.crt"


def local_names() -> tuple[list[str], list[str]]:
    """Rechnername(n) und IPv4-Adressen dieses Servers."""
    host = socket.gethostname()
    names = {host, host.lower(), "localhost"}
    try:
        fqdn = socket.getfqdn()
        if fqdn and "." in fqdn:
            names.add(fqdn.lower())
    except OSError:
        pass
    ips = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:  # bevorzugte ausgehende Adresse (funktioniert ohne echte Verbindung)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(names), sorted(ips)


def _write_key(key, path: Path) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))


def _load_or_create_ca() -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    key_path, crt_path = cert_dir() / "ca.key", ca_cert_path()
    if key_path.exists() and crt_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), None)
        return x509.load_pem_x509_certificate(crt_path.read_bytes()), key  # type: ignore[return-value]
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"OCRDMS lokale CA ({socket.gethostname()})"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OCRDMS")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_key(key, key_path)
    crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("Neue lokale Zertifizierungsstelle erstellt: %s", crt_path)
    return cert, key


def ensure_server_cert(extra_names: list[str] | None = None) -> tuple[Path, Path]:
    """Erstellt/erneuert bei Bedarf das Server-Zertifikat. Gibt (cert, key) zurück."""
    names, ips = local_names()
    names = sorted(set(names) | set(extra_names or []))
    crt_path, key_path, meta_path = cert_dir() / "server.crt", cert_dir() / "server.key", cert_dir() / "server.json"
    wanted = {"names": names, "ips": ips}
    if crt_path.exists() and key_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            cert = x509.load_pem_x509_certificate(crt_path.read_bytes())
            still_valid = cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)
            if meta == wanted and still_valid:
                return crt_path, key_path
        except Exception:
            pass

    ca_cert, ca_key = _load_or_create_ca()
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    san = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, socket.gethostname())]))
        .issuer_name(ca_cert.subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(key, key_path)
    # Kette mitliefern, damit Clients die CA zuordnen können
    crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    meta_path.write_text(json.dumps(wanted))
    log.info("Server-Zertifikat ausgestellt für %s", ", ".join(names + ips))
    return crt_path, key_path
