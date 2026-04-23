from __future__ import annotations

from dataclasses import dataclass

from astra_runtime.chat_identity import build_chat_key


def build_message_key(runtime_chat_id: int, runtime_message_id: int) -> str:
    return f"{build_chat_key(runtime_chat_id)}:{int(runtime_message_id)}"


def parse_message_key(message_key: str | None) -> tuple[int, int] | None:
    if not isinstance(message_key, str):
        return None

    prefix, separator, runtime_message_id = message_key.rpartition(":")
    if not separator:
        return None

    try:
        parsed_runtime_message_id = int(runtime_message_id)
    except ValueError:
        return None

    from astra_runtime.chat_identity import parse_chat_key

    runtime_chat_id = parse_chat_key(prefix)
    if runtime_chat_id is None:
        return None
    return runtime_chat_id, parsed_runtime_message_id


@dataclass(frozen=True, slots=True)
class MessageIdentity:
    runtime_chat_id: int
    runtime_message_id: int
    local_message_id: int | None = None

    @property
    def chat_key(self) -> str:
        return build_chat_key(self.runtime_chat_id)

    @property
    def message_key(self) -> str:
        return build_message_key(
            runtime_chat_id=self.runtime_chat_id,
            runtime_message_id=self.runtime_message_id,
        )

    def to_payload(self) -> dict[str, int | str | None]:
        return {
            "chatKey": self.chat_key,
            "messageKey": self.message_key,
            "runtimeMessageId": self.runtime_message_id,
            "localMessageId": self.local_message_id,
        }
