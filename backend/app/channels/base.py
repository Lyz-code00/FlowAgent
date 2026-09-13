from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from app.schemas.message import UnifiedMessage


class ChannelVerificationError(ValueError):
    """Raised when an inbound channel event cannot be trusted."""


class UnsupportedMessage(ValueError):
    """Raised when a channel message is outside the MVP contract."""


class ChannelAdapter(ABC):
    @abstractmethod
    def verify_event(
        self, *, body: bytes, headers: Mapping[str, str], payload: dict[str, Any]
    ) -> None:
        """Validate a channel event or raise ChannelVerificationError."""

    @abstractmethod
    def parse_event(self, payload: dict[str, Any]) -> UnifiedMessage:
        """Convert a channel event into the stable domain model."""

    @abstractmethod
    def should_handle(self, payload: dict[str, Any]) -> bool:
        """Return whether this event should trigger FlowAgent."""

    @abstractmethod
    async def send_message(self, *, source_message_id: str, content: str) -> None:
        """Send the final response back through the channel."""

    async def enrich_message(self, message: UnifiedMessage) -> UnifiedMessage:
        """Download or decode channel resources before the agent sees the message."""
        return message
