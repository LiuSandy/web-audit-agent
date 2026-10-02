"""AES-256-CBC encrypted credential storage in SQLite."""

from __future__ import annotations

import sys
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
        self.encryption_key = self.get_or_create_encryption_key()

    def get_or_create_encryption_key(self) -> bytes:
        key_env = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
        if key_env and len(key_env) == 64:
            try:
                return bytes.fromhex(key_env)
            except ValueError:
                pass

        key_path = Path.cwd() / self.KEY_FILE
        if key_path.exists():
            try:
                key_hex = key_path.read_text(encoding="utf-8").strip()
                if len(key_hex) == 64:
                    return bytes.fromhex(key_hex)
            except Exception as error:  # noqa: BLE001 - preserve source catch
                print(f"读取密钥文件失败：{error}", file=sys.stderr)

        key = os.urandom(32)
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(key.hex())
        except Exception:  # noqa: BLE001 - preserve source catch
            print("⚠️  Could not save encryption key to file. Credentials will be lost on exit.", file=sys.stderr)
        return key

    async def set(self, app_identifier: str, credentials: Credentials) -> None:
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self.encryption_key), modes.CBC(iv))
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
        """, (app_identifier, encrypted.hex(), iv.hex(), now, now))

    async def get(self, app_identifier: str) -> Credentials:
        row = self.db.execute("""
            SELECT encrypted_data, iv FROM credentials WHERE app_identifier = ?
        """, (app_identifier,)).fetchone()
        if row is None:
            raise RuntimeError(f"未找到 {app_identifier} 的登录凭据")

        cipher = Cipher(algorithms.AES(self.encryption_key), modes.CBC(bytes.fromhex(row["iv"])))
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
