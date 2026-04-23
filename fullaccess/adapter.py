from adapters.base import AdapterStub


class FullAccessAdapter(AdapterStub):
    name = "fullaccess"
    notes = (
        "Экспериментальный слой для ручной авторизации пользовательской сессии, "
        "поиска чатов, синхронизации истории и явной отправки сообщений."
    )
