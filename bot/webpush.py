"""Web-Push-Benachrichtigungen ohne Zusatzdienst (RFC 8291 + VAPID RFC 8292).

Der Bot schickt Benachrichtigungen direkt an den Push-Dienst deines Browsers
(Google, Mozilla, Apple, Microsoft). Dafür braucht es ein eigenes Schlüsselpaar,
das beim ersten Start in vapid_privat.pem angelegt wird – diese Datei geheim halten.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Nur an echte Push-Dienste der Browser senden – nie an beliebige Adressen.
ERLAUBTE_PUSH_HOSTS = (".googleapis.com", ".mozilla.com", ".mozaws.net", ".push.apple.com", ".notify.windows.com")


class PushAbgelaufen(Exception):
    """Das Gerät hat die Benachrichtigungen abbestellt – Abo löschen."""


def b64url(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).rstrip(b"=").decode()


def b64url_dekodieren(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _oeffentlich_roh(schluessel: ec.EllipticCurvePublicKey) -> bytes:
    return schluessel.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def lade_oder_erzeuge_schluessel(pfad: Path) -> ec.EllipticCurvePrivateKey:
    if pfad.exists():
        return serialization.load_pem_private_key(pfad.read_bytes(), password=None)
    schluessel = ec.generate_private_key(ec.SECP256R1())
    pfad.write_bytes(schluessel.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return schluessel


def oeffentlicher_schluessel(privat: ec.EllipticCurvePrivateKey) -> str:
    """Der Teil, den der Browser zum Abonnieren braucht (applicationServerKey)."""
    return b64url(_oeffentlich_roh(privat.public_key()))


def abo_ist_gueltig(abo: object) -> bool:
    if not isinstance(abo, dict):
        return False
    endpoint, keys = abo.get("endpoint"), abo.get("keys")
    if not isinstance(endpoint, str) or not isinstance(keys, dict) or len(endpoint) > 1000:
        return False
    teile = urlparse(endpoint)
    if teile.scheme != "https" or not (teile.hostname or "").endswith(ERLAUBTE_PUSH_HOSTS):
        return False
    try:
        return len(b64url_dekodieren(keys["p256dh"])) == 65 and len(b64url_dekodieren(keys["auth"])) == 16
    except (KeyError, TypeError, ValueError):
        return False


def verschluessele(nachricht: bytes, p256dh: str, auth: str,
                   _salz: bytes | None = None, _absender: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Verschlüsselt die Nachricht für genau ein Gerät (aes128gcm, RFC 8291)."""
    empfaenger_roh = b64url_dekodieren(p256dh)
    empfaenger = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), empfaenger_roh)
    auth_geheim = b64url_dekodieren(auth)
    absender = _absender or ec.generate_private_key(ec.SECP256R1())
    absender_roh = _oeffentlich_roh(absender.public_key())
    salz = _salz or os.urandom(16)

    gemeinsam = absender.exchange(ec.ECDH(), empfaenger)
    ikm = HKDF(hashes.SHA256(), 32, auth_geheim, b"WebPush: info\x00" + empfaenger_roh + absender_roh).derive(gemeinsam)
    cek = HKDF(hashes.SHA256(), 16, salz, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salz, b"Content-Encoding: nonce\x00").derive(ikm)
    geheimtext = AESGCM(cek).encrypt(nonce, nachricht + b"\x02", None)
    kopf = salz + (4096).to_bytes(4, "big") + bytes([len(absender_roh)]) + absender_roh
    return kopf + geheimtext


def _vapid_kopf(endpoint: str, privat: ec.EllipticCurvePrivateKey, kontakt: str) -> str:
    teile = urlparse(endpoint)
    kopf = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    inhalt = b64url(json.dumps({
        "aud": f"{teile.scheme}://{teile.netloc}",
        "exp": int(time.time()) + 12 * 3600,
        "sub": kontakt,
    }).encode())
    r, s = decode_dss_signature(privat.sign(f"{kopf}.{inhalt}".encode(), ec.ECDSA(hashes.SHA256())))
    signatur = b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={kopf}.{inhalt}.{signatur}, k={oeffentlicher_schluessel(privat)}"


def sende(abo: dict, nachricht: dict, privat: ec.EllipticCurvePrivateKey, kontakt: str,
          session: requests.Session, timeout: int = 20) -> None:
    """Schickt eine Benachrichtigung. Wirft PushAbgelaufen, wenn das Abo nicht mehr gilt."""
    if not abo_ist_gueltig(abo):
        raise PushAbgelaufen("ungültiges Abo")
    daten = json.dumps(nachricht, ensure_ascii=False).encode()[:3000]
    koerper = verschluessele(daten, abo["keys"]["p256dh"], abo["keys"]["auth"])
    r = session.post(abo["endpoint"], data=koerper, timeout=timeout, allow_redirects=False, headers={
        "Authorization": _vapid_kopf(abo["endpoint"], privat, kontakt),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": "86400",
        "Urgency": "normal",
    })
    if r.status_code in (404, 410):
        raise PushAbgelaufen(f"HTTP {r.status_code}")
    if r.status_code >= 400:
        raise requests.HTTPError(f"Push-Dienst antwortet HTTP {r.status_code}: {r.text[:200]}")
