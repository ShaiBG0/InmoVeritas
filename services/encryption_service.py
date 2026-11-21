"""
services/encryption_service.py
Cifrado AES-256-GCM. Cada expediente tiene su propia llave aleatoria.
La llave del expediente se guarda cifrada con la MASTER_KEY (del .env),
en storage/keys/, SEPARADA de los archivos cifrados.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
KEYS_DIR = BASE_DIR / "storage" / "keys"


class EncryptionError(Exception):
    pass


def _master_key() -> bytes:
    raw = os.environ.get("MASTER_KEY", "").split("#", 1)[0].strip()
    if not raw:
        raise EncryptionError("Falta MASTER_KEY en .env. Ejecuta: python init_env.py")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise EncryptionError("MASTER_KEY debe ser de 32 bytes (base64).")
    return key


def encrypt(key: bytes, data: bytes, aad: bytes = b"") -> bytes:
    """Devuelve nonce(12 bytes) + texto cifrado. Nonce nuevo en cada operación."""
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)


def create_case_key(case_id: str) -> bytes:
    key = AESGCM.generate_key(bit_length=256)
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    wrapped = encrypt(_master_key(), key, f"key:{case_id}".encode())
    (KEYS_DIR / f"{case_id}.key").write_bytes(wrapped)
    return key


def case_key_exists(case_id: str) -> bool:
    return (KEYS_DIR / f"{case_id}.key").exists()


def load_case_key(case_id: str) -> bytes:
    wrapped = (KEYS_DIR / f"{case_id}.key").read_bytes()
    return decrypt(_master_key(), wrapped, f"key:{case_id}".encode())