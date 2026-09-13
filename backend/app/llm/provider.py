import json
from abc import ABC, abstractmethod
from typing import Any, TypedDict

import httpx
from pydantic import BaseModel, Field


class ChatMessage(TypedDict, total=False):
    role: str
    content: str | list[dict[str, Any]] | None
    tool_calls: list[dict[str, Any]]
    tool_call_id: str


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMOutput(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)

    def as_assistant_message(self) -> ChatMessage:
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in self.tool_calls
            ],
        }


class LLMProvider(ABC):
    model_name: str

    @abstractmethod
    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        disable_thinking: bool = False,
    ) -> LLMOutput:
        pass


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        vision_model: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.vision_model = vision_model.strip()
        self._client = client

    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        disable_thinking: bool = False,
    ) -> LLMOutput:
        has_image = any(
            isinstance(item.get("content"), list)
            and any(
                part.get("type") == "image_url"
                for part in item.get("content") or []
                if isinstance(part, dict)
            )
            for item in messages
        )
        if has_image and not self.vision_model:
            raise RuntimeError("image input requires FLOWAGENT_LLM_VISION_MODEL")
        payload: dict[str, Any] = {
            "model": self.vision_model if has_image else self.model_name,
            "messages": messages,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": definition}
                for definition in tools
            ]
            payload["tool_choice"] = tool_choice or "auto"
        if disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=45)
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if owns_client:
                await client.aclose()

        try:
            response_message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response does not contain a message") from exc
        calls: list[ToolCall] = []
        for raw_call in response_message.get("tool_calls") or []:
            function = raw_call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {"_invalid_json": raw_arguments}
            calls.append(
                ToolCall(
                    id=str(raw_call.get("id") or "unknown"),
                    name=str(function.get("name") or "unknown"),
                    arguments=arguments,
                )
            )
        return LLMOutput(
            content=response_message.get("content"),
            tool_calls=calls,
            usage=data.get("usage") or {},
        )


class DevelopmentProvider(LLMProvider):
    """Transparent fallback that keeps local development runnable without a key."""

    model_name = "development-fallback"

    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        disable_thinking: bool = False,
    ) -> LLMOutput:
        user_messages = [item for item in messages if item.get("role") == "user"]
        latest = user_messages[-1].get("content", "") if user_messages else ""
        if isinstance(latest, list):
            latest = "[包含图片或附件的消息]"
        return LLMOutput(
            content=(
                f"FlowAgent 已收到：{latest}\n\n"
                "当前未配置 LLM API Key，因此使用本地开发响应。配置后即可启用多轮模型推理。"
            )
        )
