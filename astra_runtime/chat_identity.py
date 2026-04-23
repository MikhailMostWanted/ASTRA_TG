from __future__ import annotations

from dataclasses import dataclass


CHAT_KEY_PREFIX = "telegram"


def build_chat_key(runtime_chat_id: int) -> str:
    return f"{CHAT_KEY_PREFIX}:{int(runtime_chat_id)}"


def parse_chat_key(chat_key: str | None) -> int | None:
    if not isinstance(chat_key, str):
        return None
    prefix = f"{CHAT_KEY_PREFIX}:"
    if not chat_key.startswith(prefix):
        return None
    try:
        return int(chat_key.removeprefix(prefix))
    except ValueError:
        return None


def build_runtime_only_chat_id(runtime_chat_id: int) -> int:
    normalized = int(runtime_chat_id)
    magnitude = abs(normalized)
    if normalized >= 0:
        return -((magnitude * 2) + 1)
    return -((magnitude * 2) + 2)


def parse_runtime_only_chat_id(chat_id: int) -> int | None:
    if int(chat_id) >= 0:
        return None

    encoded = -int(chat_id)
    if encoded % 2 == 1:
        return (encoded - 1) // 2
    return -((encoded - 2) // 2)


def resolve_roster_chat_id(
    *,
    local_chat_id: int | None,
    runtime_chat_id: int,
) -> int:
    if local_chat_id is not None:
        return int(local_chat_id)
    return build_runtime_only_chat_id(runtime_chat_id)


@dataclass(frozen=True, slots=True)
class ChatIdentity:
    runtime_chat_id: int
    local_chat_id: int | None = None

    @property
    def chat_key(self) -> str:
        return build_chat_key(self.runtime_chat_id)

    @property
    def roster_chat_id(self) -> int:
        return resolve_roster_chat_id(
            local_chat_id=self.local_chat_id,
            runtime_chat_id=self.runtime_chat_id,
        )

    @property
    def workspace_available(self) -> bool:
        return self.local_chat_id is not None

    def to_payload(self) -> dict[str, int | str | bool | None]:
        return {
            "id": self.roster_chat_id,
            "localChatId": self.local_chat_id,
            "runtimeChatId": self.runtime_chat_id,
            "chatKey": self.chat_key,
            "workspaceAvailable": self.workspace_available,
        }
