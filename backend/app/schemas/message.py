from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    type: str
    key: str | None = None
    name: str | None = None
    mime_type: str | None = None
    data_base64: str | None = Field(default=None, exclude=True)
    extracted_text: str | None = None
    error: str | None = None


class UnifiedMessage(BaseModel):
    platform: Literal["feishu", "dingtalk", "wecom", "web"]
    tenant_id: str
    external_user_id: str
    internal_user_id: int | None = None
    conversation_id: str
    message_id: str
    message_type: str
    text: str
    attachments: list[Attachment] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_event: dict[str, Any] = Field(default_factory=dict, exclude=True)


class AgentResponse(BaseModel):
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
