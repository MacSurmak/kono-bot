import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger


class EncryptionError(Exception):
    """Raised when encryption or decryption operation fails."""


def _get_encryption_key() -> bytes:
    """Retrieves and validates master encryption key from environment."""
    key = os.getenv("APP_ENCRYPTION_KEY")
    if not key or not key.strip():
        raise RuntimeError(
            "CRITICAL SECURITY FAILURE: 'APP_ENCRYPTION_KEY' environment variable is missing or empty. "
            "Generate a secure key using: python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return key.strip().encode("utf-8")


def encrypt_secret(plaintext: str) -> bytes:
    """Encrypts plaintext string using Fernet authenticated symmetric cipher."""
    if not plaintext:
        return b""
    try:
        cipher = Fernet(_get_encryption_key())
        return cipher.encrypt(plaintext.encode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to encrypt secret: {e}")
        raise EncryptionError(f"Encryption failed: {e}") from e


def decrypt_secret(ciphertext: Optional[bytes]) -> str:
    """Decrypts ciphertext bytes back to original plaintext string."""
    if not ciphertext:
        return ""
    try:
        cipher = Fernet(_get_encryption_key())
        return cipher.decrypt(ciphertext).decode("utf-8")
    except InvalidToken as it:
        logger.error("Failed to decrypt secret: invalid cryptographic token or corrupted key.")
        raise EncryptionError("Invalid encryption key or corrupted secret payload") from it
    except Exception as e:
        logger.error(f"Failed to decrypt secret: {e}")
        raise EncryptionError(f"Decryption failed: {e}") from e
