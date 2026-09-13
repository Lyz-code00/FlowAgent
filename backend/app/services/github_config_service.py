import base64
import hashlib
import os
from dataclasses import dataclass

from Crypto.Cipher import AES
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import GitHubConfig


class SecretCipher:
    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("configuration encryption key is required")
        self.key = hashlib.sha256(secret.encode()).digest()

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        nonce = os.urandom(12)
        cipher = AES.new(self.key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(value.encode())
        return "v1:" + base64.urlsafe_b64encode(nonce + tag + ciphertext).decode()

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        if not value.startswith("v1:"):
            raise ValueError("unsupported encrypted secret format")
        payload = base64.urlsafe_b64decode(value[3:].encode())
        nonce, tag, ciphertext = payload[:12], payload[12:28], payload[28:]
        cipher = AES.new(self.key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag).decode()


@dataclass(frozen=True)
class GitHubRuntimeConfig:
    owner: str
    repo: str
    token: str
    default_labels: list[str]
    default_assignee: str
    member_can_create_issue: bool

    @property
    def configured(self) -> bool:
        return bool(self.owner and self.repo and self.token)


class GitHubConfigService:
    CONFIG_ID = 1

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cipher: SecretCipher,
    ) -> None:
        self.session_factory = session_factory
        self.cipher = cipher

    async def ensure_default(
        self,
        *,
        owner: str,
        repo: str,
        token: str,
        default_labels: list[str],
        default_assignee: str,
        member_can_create_issue: bool,
    ) -> GitHubRuntimeConfig:
        async with self.session_factory() as session:
            row = await session.get(GitHubConfig, self.CONFIG_ID)
            if row is None:
                row = GitHubConfig(
                    id=self.CONFIG_ID,
                    owner=owner,
                    repo=repo,
                    token_encrypted=self.cipher.encrypt(token),
                    default_labels=default_labels,
                    default_assignee=default_assignee,
                    member_can_create_issue=member_can_create_issue,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return self._runtime(row)

    async def get(self) -> GitHubRuntimeConfig:
        async with self.session_factory() as session:
            row = await session.get(GitHubConfig, self.CONFIG_ID)
            if row is None:
                raise RuntimeError("GitHub configuration is not initialized")
            return self._runtime(row)

    async def public(self) -> dict:
        config = await self.get()
        return {
            "owner": config.owner,
            "repo": config.repo,
            "token_configured": bool(config.token),
            "default_labels": config.default_labels,
            "default_assignee": config.default_assignee or None,
            "member_can_create_issue": config.member_can_create_issue,
        }

    async def update(
        self,
        *,
        owner: str,
        repo: str,
        token: str | None,
        clear_token: bool,
        default_labels: list[str],
        default_assignee: str,
        member_can_create_issue: bool,
    ) -> dict:
        async with self.session_factory() as session:
            row = await session.get(GitHubConfig, self.CONFIG_ID)
            if row is None:
                raise RuntimeError("GitHub configuration is not initialized")
            row.owner = owner
            row.repo = repo
            if clear_token:
                row.token_encrypted = ""
            elif token:
                row.token_encrypted = self.cipher.encrypt(token)
            row.default_labels = default_labels
            row.default_assignee = default_assignee
            row.member_can_create_issue = member_can_create_issue
            await session.commit()
        return await self.public()

    def _runtime(self, row: GitHubConfig) -> GitHubRuntimeConfig:
        return GitHubRuntimeConfig(
            owner=row.owner,
            repo=row.repo,
            token=self.cipher.decrypt(row.token_encrypted),
            default_labels=list(row.default_labels or []),
            default_assignee=row.default_assignee,
            member_can_create_issue=row.member_can_create_issue,
        )
