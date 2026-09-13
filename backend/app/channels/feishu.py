import base64
import hashlib
import hmac
import json
import mimetypes
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
from app.rag.parser import DocumentParseError, parse_document
from app.schemas.message import Attachment, UnifiedMessage
from app.services.transcription_service import TranscriptionService


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
        max_attachment_bytes: int = 10 * 1024 * 1024,
        transcription_service: TranscriptionService | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key
        self.bot_open_id = bot_open_id
        self.max_attachment_bytes = max_attachment_bytes
        self.transcription_service = transcription_service
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
        message_type = str(message.get("message_type") or "")
        if message_type not in {"text", "image", "file", "audio"}:
            raise UnsupportedMessage(
                "FlowAgent supports text, image, audio, Markdown, TXT and text PDF messages"
            )

        try:
            content = json.loads(message.get("content") or "{}")
        except json.JSONDecodeError as exc:
            raise UnsupportedMessage("invalid Feishu message content") from exc
        text = str(content.get("text") or "") if message_type == "text" else ""
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

        attachments: list[Attachment] = []
        if message_type == "image":
            attachments.append(
                Attachment(type="image", key=str(content.get("image_key") or ""))
            )
            text = "请分析这张图片。"
        elif message_type in {"file", "audio"}:
            name = str(content.get("file_name") or "")
            if not name:
                name = "audio.ogg" if message_type == "audio" else "attachment"
            attachments.append(
                Attachment(
                    type=message_type,
                    key=str(content.get("file_key") or ""),
                    name=name,
                )
            )
            text = "请处理这段语音。" if message_type == "audio" else f"请阅读附件：{name}"

        return UnifiedMessage(
            platform="feishu",
            tenant_id=str(payload.get("header", {}).get("tenant_key") or "default"),
            external_user_id=str(
                sender.get("sender_id", {}).get("open_id") or "unknown"
            ),
            conversation_id=str(message.get("chat_id") or ""),
            message_id=str(message.get("message_id") or ""),
            message_type=message_type,
            text=text.strip(),
            attachments=attachments,
            timestamp=timestamp,
            raw_event=payload,
        )

    async def enrich_message(self, message: UnifiedMessage) -> UnifiedMessage:
        if not message.attachments:
            return message
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        enriched: list[Attachment] = []
        try:
            token = await self._tenant_access_token(client)
            for attachment in message.attachments:
                try:
                    data, mime_type = await self._download_resource(
                        client,
                        token=token,
                        message_id=message.message_id,
                        attachment=attachment,
                    )
                    enriched.append(
                        await self._decode_attachment(attachment, data, mime_type)
                    )
                except Exception as exc:
                    enriched.append(attachment.model_copy(update={"error": str(exc)}))
        finally:
            if owns_client:
                await client.aclose()
        return message.model_copy(update={"attachments": enriched})

    async def _download_resource(
        self,
        client: httpx.AsyncClient,
        *,
        token: str,
        message_id: str,
        attachment: Attachment,
    ) -> tuple[bytes, str | None]:
        if not attachment.key:
            raise RuntimeError("消息资源缺少 file_key/image_key")
        resource_type = "image" if attachment.type == "image" else "file"
        response = await client.get(
            f"{self.API_BASE}/im/v1/messages/{message_id}/resources/{attachment.key}",
            headers={"Authorization": f"Bearer {token}"},
            params={"type": resource_type},
        )
        response.raise_for_status()
        if len(response.content) > self.max_attachment_bytes:
            raise RuntimeError(
                f"附件超过 {self.max_attachment_bytes // (1024 * 1024)} MiB 限制"
            )
        return response.content, response.headers.get("content-type")

    async def _decode_attachment(
        self,
        attachment: Attachment,
        data: bytes,
        response_mime_type: str | None,
    ) -> Attachment:
        guessed_mime = mimetypes.guess_type(attachment.name or "")[0]
        mime_type = (response_mime_type or guessed_mime or "application/octet-stream").split(";")[0]
        if attachment.type == "image":
            if mime_type == "application/octet-stream":
                mime_type = self._sniff_image_mime(data)
            return attachment.model_copy(
                update={
                    "mime_type": mime_type,
                    "data_base64": base64.b64encode(data).decode("ascii"),
                }
            )
        if attachment.type == "audio":
            if self.transcription_service is None or not self.transcription_service.configured:
                return attachment.model_copy(
                    update={"mime_type": mime_type, "error": "语音转写服务尚未配置"}
                )
            transcript = await self.transcription_service.transcribe(
                data=data,
                filename=attachment.name or "audio.ogg",
                mime_type=mime_type,
            )
            return attachment.model_copy(
                update={"mime_type": mime_type, "extracted_text": transcript}
            )
        try:
            sections = parse_document(attachment.name or "attachment", data)
            extracted = "\n\n".join(section.text for section in sections).strip()
            return attachment.model_copy(
                update={"mime_type": mime_type, "extracted_text": extracted[:100_000]}
            )
        except DocumentParseError as exc:
            return attachment.model_copy(update={"mime_type": mime_type, "error": str(exc)})

    @staticmethod
    def _sniff_image_mime(data: bytes) -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"
        raise RuntimeError("无法识别图片格式")

    async def send_message(self, *, source_message_id: str, content: str) -> None:
        if not self.app_id or not self.app_secret:
            raise RuntimeError("Feishu app credentials are not configured")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=10)
        try:
            token = await self._tenant_access_token(client)
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

    async def send_file(
        self,
        *,
        source_message_id: str,
        name: str,
        content_type: str,
        data: bytes,
    ) -> None:
        if not self.app_id or not self.app_secret:
            raise RuntimeError("Feishu app credentials are not configured")
        if not data:
            raise RuntimeError("generated file is empty")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            token = await self._tenant_access_token(client)
            upload_response = await client.post(
                f"{self.API_BASE}/im/v1/files",
                headers={"Authorization": f"Bearer {token}"},
                data={"file_type": "stream", "file_name": name},
                files={"file": (name, data, content_type)},
            )
            upload_response.raise_for_status()
            upload_payload = upload_response.json()
            file_key = (upload_payload.get("data") or {}).get("file_key")
            if upload_payload.get("code") != 0 or not file_key:
                raise RuntimeError(
                    "failed to upload file through Feishu: "
                    f"{upload_payload.get('msg', 'unknown error')}"
                )

            reply_response = await client.post(
                f"{self.API_BASE}/im/v1/messages/{source_message_id}/reply",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "msg_type": "file",
                    "content": json.dumps({"file_key": file_key}),
                },
            )
            reply_response.raise_for_status()
            reply_payload = reply_response.json()
            if reply_payload.get("code") != 0:
                raise RuntimeError(
                    "failed to reply with file through Feishu: "
                    f"{reply_payload.get('msg', 'unknown error')}"
                )
        finally:
            if owns_client:
                await client.aclose()

    async def _tenant_access_token(self, client: httpx.AsyncClient) -> str:
        if not self.app_id or not self.app_secret:
            raise RuntimeError("Feishu app credentials are not configured")
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
        return str(token)
