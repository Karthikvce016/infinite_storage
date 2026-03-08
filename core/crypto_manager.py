"""
crypto_manager.py – AES-256-GCM file encryption / decryption for Telegram Drive.

Pipeline:
    original_file  →  AES-256-GCM encrypt  →  encrypted_file  →  split  →  upload
    download       →  merge                 →  AES-256-GCM decrypt  →  original_file
"""

import os
import secrets
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from config.settings import PBKDF2_ITERATIONS, SALT_FILE

# 96-bit nonce is recommended for AES-GCM
_NONCE_SIZE = 12
# AESGCM tag is 16 bytes, appended automatically
_READ_BLOCK = 64 * 1024 * 1024  # 64 MB streaming block


# ──────────────────────────────────────────────
# Key derivation
# ──────────────────────────────────────────────
def _load_or_create_salt() -> bytes:
    """Persist a random salt so the same passphrase always yields the same key."""
    if SALT_FILE.exists():
        return SALT_FILE.read_bytes()
    salt = secrets.token_bytes(32)
    SALT_FILE.write_bytes(salt)
    return salt


def derive_key(passphrase: str) -> bytes:
    """Derive a 256-bit AES key from a user passphrase via PBKDF2-HMAC-SHA256."""
    salt = _load_or_create_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive(passphrase.encode("utf-8"))


# ──────────────────────────────────────────────
# Encrypt / decrypt (streaming for large files)
# ──────────────────────────────────────────────
def encrypt_file(src: Path, dst: Path, key: bytes) -> None:
    """
    Encrypt *src* to *dst* using AES-256-GCM.

    File layout:  [12-byte nonce][ciphertext + 16-byte tag]

    For files larger than _READ_BLOCK we still read the whole plaintext
    into memory in order to use the single-shot AESGCM API which handles
    the tag automatically.  For truly huge files (>~2 GB) the caller
    should chunk *before* encrypting each chunk individually.
    """
    nonce = os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(key)

    plaintext = src.read_bytes()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    with open(dst, "wb") as f:
        f.write(nonce)
        f.write(ciphertext)


def decrypt_file(src: Path, dst: Path, key: bytes) -> None:
    """
    Decrypt a file produced by *encrypt_file*.
    """
    raw = src.read_bytes()
    nonce = raw[:_NONCE_SIZE]
    ciphertext = raw[_NONCE_SIZE:]

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    dst.write_bytes(plaintext)

