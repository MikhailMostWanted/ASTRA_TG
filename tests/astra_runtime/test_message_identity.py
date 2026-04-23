from astra_runtime.message_identity import MessageIdentity, build_message_key, parse_message_key


def test_message_key_roundtrip_keeps_runtime_chat_and_message_ids() -> None:
    message_key = build_message_key(runtime_chat_id=-100300, runtime_message_id=512)

    assert message_key == "telegram:-100300:512"
    assert parse_message_key(message_key) == (-100300, 512)


def test_message_identity_payload_exposes_stable_ui_fields() -> None:
    identity = MessageIdentity(
        runtime_chat_id=-100300,
        runtime_message_id=512,
        local_message_id=77,
    )

    assert identity.chat_key == "telegram:-100300"
    assert identity.message_key == "telegram:-100300:512"
    assert identity.to_payload() == {
        "chatKey": "telegram:-100300",
        "messageKey": "telegram:-100300:512",
        "runtimeMessageId": 512,
        "localMessageId": 77,
    }
