"""Loads stored credentials for authenticated sessions."""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Literal, NotRequired, TypedDict

from src.auth.credential_storage import Credentials, CredentialStorage


class AuthConfig(TypedDict):
    storageType: NotRequired[Literal["sqlite", "memory"]]


class CredentialProvider:
    def __init__(self, db: sqlite3.Connection, config: AuthConfig | None = None) -> None:
        self.storage = CredentialStorage(db)

    async def get_credentials(self, app_identifier: str) -> Credentials:
        env_creds = self.get_from_environment(app_identifier)
        if env_creds:
            return env_creds
        return await self.storage.get(app_identifier)

    async def store_credentials(self, app_identifier: str, credentials: Credentials) -> None:
        await self.storage.set(app_identifier, credentials)

    async def list_credentials(self) -> list[str]:
        return await self.storage.list()

    def get_from_environment(self, app_identifier: str) -> Credentials | None:
        prefix = "AUTH_" + re.sub(r"[^A-Z0-9]", "_", app_identifier.upper())
        username = os.environ.get(f"{prefix}_USERNAME")
        email = os.environ.get(f"{prefix}_EMAIL")
        password = os.environ.get(f"{prefix}_PASSWORD")
        totp_secret = os.environ.get(f"{prefix}_TOTP_SECRET")
        if not password:
            return None
        result: Credentials = {"password": password}
        if username is not None:
            result["username"] = username
        if email is not None:
            result["email"] = email
        if totp_secret is not None:
            result["totpSecret"] = totp_secret
        return result
