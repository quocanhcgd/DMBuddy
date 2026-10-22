import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.models.printer import Printer
from backend.app.services.flashforge.secrets import decrypt_check_code, encrypt_check_code


def _configure_key(monkeypatch) -> None:
    from cryptography.fernet import Fernet

    import backend.app.core.encryption as encryption

    monkeypatch.setenv("MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(encryption, "_fernet_instance", None)


def test_flashforge_check_code_is_encrypted_and_roundtrips(monkeypatch):
    _configure_key(monkeypatch)

    stored = encrypt_check_code("local-lan-check-code")

    assert stored.startswith("fernet:")
    assert stored != "local-lan-check-code"
    assert decrypt_check_code(stored) == "local-lan-check-code"


def test_flashforge_check_code_refuses_plaintext_fallback(monkeypatch):
    import backend.app.services.flashforge.secrets as secrets

    monkeypatch.setattr(secrets, "mfa_encrypt", lambda value: value)
    with pytest.raises(RuntimeError, match="refusing plaintext storage"):
        encrypt_check_code("local-lan-check-code")


@pytest.mark.asyncio
async def test_migration_encrypts_legacy_flashforge_check_code_only(db_session, monkeypatch):
    from backend.app.core import database

    _configure_key(monkeypatch)
    test_sessions = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session", test_sessions)

    legacy = Printer(
        name="Legacy AD5M",
        serial_number="FF-LEGACY-01",
        ip_address="192.168.1.60",
        access_code="flashforge",
        provider="flashforge_ad5m",
        auth_token="legacy-check-code",
        model="Adventurer 5M Pro",
    )
    unrelated = Printer(
        name="Moonraker",
        serial_number="KLIPPER-LEGACY-01",
        ip_address="192.168.1.61",
        access_code="moonraker",
        provider="klipper",
        auth_token="moonraker-token",
        model="Voron",
    )
    db_session.add_all([legacy, unrelated])
    await db_session.commit()

    await database._migrate_encrypt_legacy_secrets()
    await database._migrate_encrypt_legacy_secrets()

    await db_session.refresh(legacy)
    await db_session.refresh(unrelated)
    assert legacy.auth_token.startswith("fernet:")
    assert decrypt_check_code(legacy.auth_token) == "legacy-check-code"
    assert unrelated.auth_token == "moonraker-token"
