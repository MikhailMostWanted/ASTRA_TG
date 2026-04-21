from adapters.base import AdapterStub


class FullAccessAdapter(AdapterStub):
    name = "fullaccess"
    notes = (
        "Experimental read-only scaffold for manual user-session auth, "
        "chat discovery and one-chat-at-a-time history sync into message_store."
    )
