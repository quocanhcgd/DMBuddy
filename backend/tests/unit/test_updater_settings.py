"""Environment variable compatibility for the self-update sidecar."""

from updater.app.settings import Settings


def test_updater_prefers_dmbuddy_environment_names(monkeypatch):
    monkeypatch.setenv("DMBUDDY_UPDATER_TOKEN", "new-token")
    monkeypatch.setenv("PRINTBUDDY_UPDATER_TOKEN", "legacy-token")

    assert Settings().updater_token == "new-token"


def test_updater_accepts_printbuddy_environment_names(monkeypatch):
    monkeypatch.delenv("DMBUDDY_UPDATER_TOKEN", raising=False)
    monkeypatch.setenv("PRINTBUDDY_UPDATER_TOKEN", "legacy-token")

    assert Settings().updater_token == "legacy-token"
