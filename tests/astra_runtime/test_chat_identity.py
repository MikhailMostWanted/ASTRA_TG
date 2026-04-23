from astra_runtime.chat_identity import (
    ChatIdentity,
    build_runtime_only_chat_id,
    parse_runtime_only_chat_id,
)


def test_runtime_only_chat_id_roundtrip_handles_private_and_group_peers() -> None:
    for runtime_chat_id in (42, -100500, -7, 0):
        synthetic = build_runtime_only_chat_id(runtime_chat_id)
        assert synthetic < 0
        assert parse_runtime_only_chat_id(synthetic) == runtime_chat_id


def test_chat_identity_payload_exposes_clear_local_and_runtime_fields() -> None:
    identity = ChatIdentity(runtime_chat_id=-100300, local_chat_id=17)

    assert identity.roster_chat_id == 17
    assert identity.chat_key == "telegram:-100300"
    assert identity.to_payload() == {
        "id": 17,
        "localChatId": 17,
        "runtimeChatId": -100300,
        "chatKey": "telegram:-100300",
        "workspaceAvailable": True,
    }
