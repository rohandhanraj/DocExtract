"""AES-256-GCM file encryption / decryption service.

File format (prepended to ciphertext)::

    [12-byte nonce][16-byte auth tag][…ciphertext…]

*   **Nonce** — 12 random bytes generated per-file.
*   **Auth tag** — 16 bytes produced by GCM; verifies no tampering.
*   **Decrypt key** — 32-byte AES-256 key stored hex-encoded in
    ``users.decrypt_key``.

Why GCM?  It provides *authenticated encryption* — encrypts AND verifies
integrity in a single pass.  CBC only encrypts (no tamper detection),
CTR encrypts but needs a separate HMAC.  GCM bundles both, is
parallelisable, and is the standard for TLS 1.3.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────
NONCE_SIZE = 12   # bytes — recommended for GCM
TAG_SIZE = 16     # bytes — GCM auth tag


def encrypt_file(plain_path: str, encrypted_path: str, hex_key: str) -> str:
    """Encrypt a file with AES-256-GCM.

    Parameters
    ----------
    plain_path:
        Path to the plaintext source file.
    encrypted_path:
        Destination path for the encrypted output.
    hex_key:
        Hex-encoded 32-byte (64 hex chars) AES-256 key.

    Returns
    -------
    str
        The ``encrypted_path`` written to.
    """
    key = bytes.fromhex(hex_key)
    if len(key) != 32:
        raise ValueError(f"AES-256 key must be 32 bytes, got {len(key)}")

    nonce = get_random_bytes(NONCE_SIZE)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

    plaintext = Path(plain_path).read_bytes()
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)

    os.makedirs(os.path.dirname(encrypted_path) or ".", exist_ok=True)
    with open(encrypted_path, "wb") as f:
        f.write(nonce)       # 12 bytes
        f.write(tag)         # 16 bytes
        f.write(ciphertext)  # rest

    logger.info(
        "Encrypted %s → %s (%d bytes)",
        plain_path, encrypted_path, len(ciphertext),
    )
    return encrypted_path


def decrypt_file(encrypted_path: str, decrypted_path: str, hex_key: str) -> str:
    """Decrypt an AES-256-GCM encrypted file.

    Parameters
    ----------
    encrypted_path:
        Path to the encrypted file (nonce‖tag‖ciphertext).
    decrypted_path:
        Destination path for the decrypted output.
    hex_key:
        Hex-encoded 32-byte AES-256 key.

    Returns
    -------
    str
        The ``decrypted_path`` written to.

    Raises
    ------
    ValueError
        If the auth tag verification fails (file tampered).
    """
    key = bytes.fromhex(hex_key)
    if len(key) != 32:
        raise ValueError(f"AES-256 key must be 32 bytes, got {len(key)}")

    raw = Path(encrypted_path).read_bytes()
    if len(raw) < NONCE_SIZE + TAG_SIZE:
        raise ValueError("Encrypted file too short — missing nonce/tag")

    nonce = raw[:NONCE_SIZE]
    tag = raw[NONCE_SIZE : NONCE_SIZE + TAG_SIZE]
    ciphertext = raw[NONCE_SIZE + TAG_SIZE :]

    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    try:
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError as exc:
        raise ValueError(
            f"Decryption failed for {encrypted_path} — file may be tampered"
        ) from exc

    os.makedirs(os.path.dirname(decrypted_path) or ".", exist_ok=True)
    Path(decrypted_path).write_bytes(plaintext)

    logger.info(
        "Decrypted %s → %s (%d bytes)",
        encrypted_path, decrypted_path, len(plaintext),
    )
    return decrypted_path


def passthrough_copy(src: str, dst: str) -> str:
    """No-op fallback — copies file unchanged when encryption is disabled."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copy2(src, dst)
    logger.info("Passthrough copy %s → %s", src, dst)
    return dst
