class ProviderError(RuntimeError):
    """Базовая ошибка provider layer."""


class ProviderUnavailableError(ProviderError):
    """Провайдер недоступен по конфигурации или сети."""


class ProviderResponseError(ProviderError):
    """Провайдер вернул неожиданный или невалидный ответ."""
