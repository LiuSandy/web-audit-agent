"""AES-256-CBC encrypted credential storage in SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import NotRequired, TypedDict

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class Credentials(TypedDict):
    password: str
    username: NotRequired[str]
    email: NotRequired[str]
    totpSecret: NotRequired[str]
    additionalFields: NotRequired[dict[str, str]]


class CredentialStorage:
    KEY_FILE = ".auth.key"

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.encryptionKey = self.getOrCreateEncryptionKey()

    def getOrCreateEncryptionKey(self) -> bytes:
        keyEnv = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
        if keyEnv and len(keyEnv) == 64:
            try:
                return bytes.fromhex(keyEnv)
            except ValueError:
                pass

        keyPath = Path.cwd() / self.KEY_FILE
        if keyPath.exists():
            try:
                keyHex = keyPath.read_text(encoding="utf-8").strip()
                if len(keyHex) == 64:
                    return bytes.fromhex(keyHex)
            except Exception as error:  # noqa: BLE001 - preserve source catch
                print(f"读取密钥文件失败：{error}")

        key = os.urandom(32)
        try:
            descriptor = os.open(keyPath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(key.hex())
        except Exception:  # noqa: BLE001 - preserve source catch
            print("⚠️  Could not save encryption key to file. Credentials will be lost on exit.")
        return key

    async def set(self, appIdentifier: str, credentials: Credentials) -> None:
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self.encryptionKey), modes.CBC(iv))
        data = json.dumps(credentials, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        padder = padding.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        now = int(time.time() * 1000)
        self.db.execute("""
            INSERT OR REPLACE INTO credentials
            (app_identifier, encrypted_data, iv, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (appIdentifier, encrypted.hex(), iv.hex(), now, now))

    async def get(self, appIdentifier: str) -> Credentials:
        row = self.db.execute("""
            SELECT encrypted_data, iv FROM credentials WHERE app_identifier = ?
        """, (appIdentifier,)).fetchone()
        if row is None:
            raise RuntimeError(f"未找到 {appIdentifier} 的登录凭据")

        cipher = Cipher(algorithms.AES(self.encryptionKey), modes.CBC(bytes.fromhex(row["iv"])))
        decryptor = cipher.decryptor()
        padded = decryptor.update(bytes.fromhex(row["encrypted_data"])) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        data = unpadder.update(padded) + unpadder.finalize()
        return json.loads(data.decode("utf-8"))

    async def list(self) -> list[str]:
        rows = self.db.execute(
            "SELECT app_identifier FROM credentials ORDER BY updated_at DESC"
        ).fetchall()
        return [row["app_identifier"] for row in rows]

    def close(self) -> None:
        self.db.close()
