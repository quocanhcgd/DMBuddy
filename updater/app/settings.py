from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    updater_token: str = Field(
        default="", validation_alias=AliasChoices("DMBUDDY_UPDATER_TOKEN", "PRINTBUDDY_UPDATER_TOKEN")
    )
    compose_file: Path = Field(
        default=Path("/host/docker-compose.yml"),
        validation_alias=AliasChoices("DMBUDDY_COMPOSE_FILE", "PRINTBUDDY_COMPOSE_FILE"),
    )
    compose_project: str = Field(
        default="printbuddy", validation_alias=AliasChoices("DMBUDDY_COMPOSE_PROJECT", "PRINTBUDDY_COMPOSE_PROJECT")
    )
    service_name: str = Field(
        default="printbuddy", validation_alias=AliasChoices("DMBUDDY_SERVICE_NAME", "PRINTBUDDY_SERVICE_NAME")
    )
    allowed_image: str = Field(
        default="docker.io/vmhomelabde/printbuddy",
        validation_alias=AliasChoices("DMBUDDY_ALLOWED_IMAGE", "PRINTBUDDY_ALLOWED_IMAGE"),
    )
    updater_port: int = Field(
        default=8787, validation_alias=AliasChoices("DMBUDDY_UPDATER_PORT", "PRINTBUDDY_UPDATER_PORT")
    )
    command_timeout_seconds: int = Field(
        default=600,
        validation_alias=AliasChoices("DMBUDDY_UPDATE_TIMEOUT_SECONDS", "PRINTBUDDY_UPDATE_TIMEOUT_SECONDS"),
    )

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
