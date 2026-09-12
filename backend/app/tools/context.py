from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class ToolContext:
    tenant_id: int
    user_id: int
    user_role: str
    conversation_id: int
    source_message_id: int
    external_message_id: str

    def operation_id(self, tool_name: str) -> str:
        value = f"{self.conversation_id}:{self.source_message_id}:{tool_name}"
        return sha256(value.encode()).hexdigest()
