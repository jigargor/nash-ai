from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.fernet_key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()


def rotate_secret(old_ciphertext: bytes, new_fernet_key: str) -> bytes:
    """Re-encrypt with a new key. Use during Fernet key rotation."""
    plaintext = decrypt_secret(old_ciphertext)
    return Fernet(new_fernet_key.encode()).encrypt(plaintext.encode())


__all__ = ["encrypt_secret", "decrypt_secret", "rotate_secret", "InvalidToken"]
