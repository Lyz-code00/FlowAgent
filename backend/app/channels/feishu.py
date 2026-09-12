import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import httpx

from app.channels.base import (
    ChannelAdapter,
    ChannelVerificationError,
    UnsupportedMessage,
)
from app.schemas.message import UnifiedMessage


class FeishuAdapter(ChannelAdapter):
    API_BASE = "https://open.feishu.cn/open-apis"

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        verification_token: str = "",
        encrypt_key: str = "",
        bot_open_id: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key
        self.bot_open_id = bot_open_id
        self._client = client

    def verify_event(
        self, *, body: bytes, headers: Mapping[str, str], payload: dict[str, Any]
    ) -> None:
        token = payload.get("token") or payload.get("header", {}).get("token")
        if self.verification_token and not hmac.compare_digest(
            str(token or ""), self.verification_token
        ):
            raise ChannelVerificationError("invalid Feishu verification token")

        if not self.encrypt_key:
            return

        timestamp = headers.get("x-lark-request-timestamp", "")
        nonce = headers.get("x-lark-request-nonce", "")
        signature = headers.get("x-lark-signature", "")
        if not timestamp or not nonce or not signature:
            raise ChannelVerificationError("missing Feishu signature headers")
        expected = hashlib.sha256(
            timestamp.encode() + nonce.encode() + self.encrypt_key.encode() + body
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ChannelVerificationError("invalid Feishu request signature")

    def should_handle(self, payload: dict[str, Any]) -> bool:
        header = payload.get("header", {})
        if header.get("event_type") != "im.message.receive_v1":
            return False
        event = payload.get("event", {})
        message = event.get("message", {})
        if message.get("message_type") != "text":
            return False
        if message.get("chat_type") == "p2p":
            return True
        mentions = message.get("mentions") or []
        if self.bot_open_id:
            return any(
                item.get("id", {}).get("open_id") == self.bot_open_id
                for item in mentions
            )
        return bool(mentions)

    def parse_event(self, payload: dict[str, Any]) -> UnifiedMessage:
        event = payload.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})
        if message.get("message_type") != "text":
            raise UnsupportedMessage("FlowAgent v0.1 only supports text messages")

        try:
            content = json.loads(message.get("content") or "{}")
        except json.JSONDecodeError as exc:
            raise UnsupportedMessage("invalid Feishu text content") from exc
        text = str(content.get("text") or "")
        for mention in message.get("mentions") or []:
            key = mention.get("key")
            name = mention.get("name")
            if key:
                text = text.replace(key, "")
            if name:
                text = re.sub(rf"@{re.escape(name)}\s*", "", text)

        create_time = message.get("create_time")
        timestamp = datetime.now(timezone.utc)
        if create_time:
            try:
                raw_timestamp = int(create_time)
                if raw_timestamp > 10_000_000_000:
                    raw_timestamp //= 1000
                timestamp = datetime.fromtimestamp(raw_timestamp, timezone.utc)
            except (TypeError, ValueError, OSError):
                pass

        return UnifiedMessage(
            platform="feishu",
            tenant_id=str(payload.get("header", {}).get("tenant_key") or "default"),
            external_user_id=str(
                sender.get("sender_id", {}).get("open_id") or "unknown"
            ),
            conversation_id=str(message.get("chat_id") or ""),
            message_id=str(message.get("message_id") or ""),
            message_type="text",
            text=text.strip(),
            timestamp=timestamp,
            raw_event=payload,
        )

    async def send_message(self, *, source_message_id: str, content: str) -> None:
        if not self.app_id or not self.app_secret:
            raise RuntimeError("Feishu app credentials are not configured")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=10)
        try:
            token_response = await client.post(
                f"{self.API_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            token = token_payload.get("tenant_access_token")
            if token_payload.get("code") != 0 or not token:
                raise RuntimeError(
                    f"failed to obtain Feishu tenant token: {token_payload.get('msg', 'unknown error')}"
                )
            reply_response = await client.post(
                f"{self.API_BASE}/im/v1/messages/{source_message_id}/reply",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "msg_type": "text",
                    "content": json.dumps({"text": content}, ensure_ascii=False),
                },
            )
            reply_response.raise_for_status()
            reply_payload = reply_response.json()
            if reply_payload.get("code") != 0:
                raise RuntimeError(
                    f"failed to reply through Feishu: {reply_payload.get('msg', 'unknown error')}"
                )
        finally:
            if owns_client:
                await client.aclose()
