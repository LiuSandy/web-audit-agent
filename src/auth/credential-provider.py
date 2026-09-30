"""Loads stored credentials for authenticated sessions."""

from __future__ import annotations

import importlib
import os
import re
import sqlite3
from typing import Literal, NotRequired, TypedDict

CredentialStorage = importlib.import_module("src.auth.credential-storage").CredentialStorage
Credentials = importlib.import_module("src.auth.credential-storage").Credentials


class AuthConfig(TypedDict):
    storageType: NotRequired[Literal["sqlite", "memory"]]


class CredentialProvider:
    def __init__(self, db: sqlite3.Connection, config: AuthConfig | None = None) -> None:
        self.storage = CredentialStorage(db)

    async def getCredentials(self, appIdentifier: str) -> Credentials:
        envCreds = self.getFromEnvironment(appIdentifier)
        if envCreds:
            return envCreds
        return await self.storage.get(appIdentifier)

    async def storeCredentials(self, appIdentifier: str, credentials: Credentials) -> None:
        await self.storage.set(appIdentifier, credentials)

    async def listCredentials(self) -> list[str]:
        return await self.storage.list()

    def getFromEnvironment(self, appIdentifier: str) -> Credentials | None:
        prefix = "AUTH_" + re.sub(r"[^A-Z0-9]", "_", appIdentifier.upper())
        username = os.environ.get(f"{prefix}_USERNAME")
        email = os.environ.get(f"{prefix}_EMAIL")
        password = os.environ.get(f"{prefix}_PASSWORD")
        totpSecret = os.environ.get(f"{prefix}_TOTP_SECRET")
        if not password:
            return None
        result: Credentials = {"password": password}
        if username is not None:
            result["username"] = username
        if email is not None:
            result["email"] = email
        if totpSecret is not None:
            result["totpSecret"] = totpSecret
        return result
