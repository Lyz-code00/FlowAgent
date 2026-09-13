import hashlib
import json

import pytest
import httpx

from app.channels.base import ChannelVerificationError
from app.channels.feishu import FeishuAdapter


def event_payload(*, chat_type: str = "group", mentions: list | None = None) -> dict:
    return {
        "header": {"event_type": "im.message.receive_v1", "tenant_key": "tenant-1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou-user"}},
            "message": {
                "message_id": "om-1",
                "chat_id": "oc-1",
                "chat_type": chat_type,
                "message_type": "text",
                "content": json.dumps({"text": "@_user_1 登录 401 怎么处理？"}),
                "mentions": mentions
                if mentions is not None
                else [
                    {
                        "key": "@_user_1",
                        "name": "FlowAgent",
                        "id": {"open_id": "ou-bot"},
                    }
                ],
                "create_time": "1757656800000",
            },
        },
    }


def test_parse_event_builds_unified_message_and_removes_mention() -> None:
    adapter = FeishuAdapter(app_id="", app_secret="", bot_open_id="ou-bot")
    message = adapter.parse_event(event_payload())

    assert message.platform == "feishu"
    assert message.tenant_id == "tenant-1"
    assert message.external_user_id == "ou-user"
    assert message.conversation_id == "oc-1"
    assert message.message_id == "om-1"
    assert message.text == "登录 401 怎么处理？"


def test_group_message_requires_bot_mention() -> None:
    adapter = FeishuAdapter(app_id="", app_secret="", bot_open_id="ou-bot")
    assert adapter.should_handle(event_payload()) is True
    assert adapter.should_handle(event_payload(mentions=[])) is False
    assert adapter.should_handle(event_payload(chat_type="p2p", mentions=[])) is True


def test_verification_token_and_signature() -> None:
    body = b'{"token":"verify-me"}'
    timestamp = "123"
    nonce = "abc"
    encrypt_key = "secret"
    signature = hashlib.sha256(
        timestamp.encode() + nonce.encode() + encrypt_key.encode() + body
    ).hexdigest()
    adapter = FeishuAdapter(
        app_id="",
        app_secret="",
        verification_token="verify-me",
        encrypt_key=encrypt_key,
    )
    adapter.verify_event(
        body=body,
        headers={
            "x-lark-request-timestamp": timestamp,
            "x-lark-request-nonce": nonce,
            "x-lark-signature": signature,
        },
        payload={"token": "verify-me"},
    )

    with pytest.raises(ChannelVerificationError):
        adapter.verify_event(
            body=body,
            headers={
                "x-lark-request-timestamp": timestamp,
                "x-lark-request-nonce": nonce,
                "x-lark-signature": "bad",
            },
            payload={"token": "verify-me"},
        )


def test_parse_image_event_builds_attachment() -> None:
    payload = event_payload(chat_type="p2p", mentions=[])
    payload["event"]["message"].update(
        {
            "message_type": "image",
            "content": json.dumps({"image_key": "img-key"}),
        }
    )
    message = FeishuAdapter(app_id="", app_secret="").parse_event(payload)
    assert message.message_type == "image"
    assert message.attachments[0].key == "img-key"
    assert message.attachments[0].type == "image"


async def test_enrich_image_downloads_resource_as_base64() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "tenant-token"}
            )
        assert request.url.path.endswith("/resources/img-key")
        assert request.url.params["type"] == "image"
        assert request.headers["Authorization"] == "Bearer tenant-token"
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nimage")

    payload = event_payload(chat_type="p2p", mentions=[])
    payload["event"]["message"].update(
        {
            "message_type": "image",
            "content": json.dumps({"image_key": "img-key"}),
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = FeishuAdapter(
            app_id="app", app_secret="secret", client=client
        )
        message = await adapter.enrich_message(adapter.parse_event(payload))
    assert message.attachments[0].mime_type == "image/png"
    assert message.attachments[0].data_base64 is not None


async def test_enrich_text_file_extracts_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "tenant-token"}
            )
        return httpx.Response(200, content="待办：修复登录问题".encode())

    payload = event_payload(chat_type="p2p", mentions=[])
    payload["event"]["message"].update(
        {
            "message_type": "file",
            "content": json.dumps(
                {"file_key": "file-key", "file_name": "requirements.txt"}
            ),
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = FeishuAdapter(
            app_id="app", app_secret="secret", client=client
        )
        message = await adapter.enrich_message(adapter.parse_event(payload))
    assert message.attachments[0].extracted_text == "待办：修复登录问题"
