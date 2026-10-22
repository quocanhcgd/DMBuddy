"""At-rest protection for FlashForge LAN check codes."""

from backend.app.core.encryption import mfa_decrypt, mfa_encrypt

_PREFIX = "fernet:"


def encrypt_check_code(check_code: str) -> str:
    value = str(check_code or "").strip()
    if not value:
        raise ValueError("FlashForge check code is required")
    encrypted = mfa_encrypt(value)
    if not encrypted.startswith(_PREFIX):
        raise RuntimeError("FlashForge check-code encryption is unavailable; refusing plaintext storage")
    return encrypted


def decrypt_check_code(stored_value: str | None) -> str:
    value = str(stored_value or "")
    if not value:
        return ""
    return mfa_decrypt(value) if value.startswith(_PREFIX) else value
