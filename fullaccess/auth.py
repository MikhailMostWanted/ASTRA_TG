from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from config.settings import Settings
from fullaccess.client import (
    FullAccessClientFactory,
    FullAccessPasswordRequiredError,
    build_fullaccess_client,
    telethon_is_available,
)
from fullaccess.models import (
    FullAccessConfig,
    FullAccessLoginResult,
    FullAccessLogoutResult,
    FullAccessStatusReport,
    PendingAuthState,
)
from storage.repositories import MessageRepository, SettingRepository


PENDING_AUTH_KEY = "fullaccess.auth.pending"


@dataclass(slots=True)
class FullAccessAuthService:
    settings: Settings
    setting_repository: SettingRepository
    message_repository: MessageRepository
    client_factory: FullAccessClientFactory = build_fullaccess_client
    transport_available: bool | None = None

    async def build_status_report(self) -> FullAccessStatusReport:
        config = FullAccessConfig.from_settings(self.settings)
        pending_state = await self._load_pending_auth()
        session_exists = config.session_path.exists()
        synced_chat_count = await self.message_repository.count_distinct_chats_by_source_adapter(
            "fullaccess"
        )
        synced_message_count = await self.message_repository.count_messages_by_source_adapter(
            "fullaccess"
        )
        transport_available = self._transport_available()
        authorized = False
        reason_parts: list[str] = []

        if not config.requested_readonly:
            reason_parts.append(
                "FULLACCESS_READONLY=false игнорируется: слой принудительно остаётся read-only."
            )

        if not config.enabled:
            reason_parts.append("FULLACCESS_ENABLED=false, experimental слой выключен.")
        elif not config.api_credentials_configured:
            reason_parts.append("Нужно задать FULLACCESS_API_ID и FULLACCESS_API_HASH.")
        elif not transport_available:
            reason_parts.append(
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'."
            )
        else:
            try:
                authorized = await self.client_factory(config).is_authorized()
            except (RuntimeError, ValueError) as error:
                reason_parts.append(f"Не удалось проверить авторизацию: {error}")
            else:
                if authorized:
                    reason_parts.append("Experimental full-access готов к ручному чтению и sync.")
                elif pending_state is not None:
                    reason_parts.append("Код уже запрошен, жду подтверждение входа.")
                elif session_exists:
                    reason_parts.append("Локальная session найдена, но пользователь не авторизован.")
                elif not config.phone_configured:
                    reason_parts.append("Нужно задать FULLACCESS_PHONE, чтобы запросить код входа.")
                else:
                    reason_parts.append("Можно запрашивать код авторизации через /fullaccess_login.")

        return FullAccessStatusReport(
            enabled=config.enabled,
            api_credentials_configured=config.api_credentials_configured,
            phone_configured=config.phone_configured,
            session_path=config.session_path,
            session_exists=session_exists,
            authorized=authorized,
            telethon_available=transport_available,
            requested_readonly=config.requested_readonly,
            effective_readonly=config.effective_readonly,
            sync_limit=config.sync_limit,
            pending_login=pending_state is not None,
            synced_chat_count=synced_chat_count,
            synced_message_count=synced_message_count,
            ready_for_manual_sync=(
                config.enabled
                and config.api_credentials_configured
                and transport_available
                and config.effective_readonly
                and authorized
            ),
            reason=" ".join(reason_parts).strip(),
        )

    async def begin_login(self) -> FullAccessLoginResult:
        config = self._require_login_prerequisites()
        client = self.client_factory(config)
        if await client.is_authorized():
            return FullAccessLoginResult(
                kind="already_authorized",
                phone=config.phone,
            )

        phone_code_hash = await client.request_login_code(config.phone or "")
        await self.setting_repository.set_value(
            key=PENDING_AUTH_KEY,
            value_json={
                "phone": config.phone,
                "phone_code_hash": phone_code_hash,
                "requested_at": datetime.now(UTC).isoformat(),
            },
            value_text=None,
        )
        return FullAccessLoginResult(
            kind="code_requested",
            phone=config.phone,
            instructions=(
                "Отправь в бот /fullaccess_login <код>.",
                "Если Telegram попросит пароль 2FA, заверши вход локально: python -m fullaccess.cli login --code <код>.",
            ),
        )

    async def complete_login(
        self,
        code: str,
        *,
        password_callback: Callable[[], str] | None = None,
    ) -> FullAccessLoginResult:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("Код Telegram пустой. Сначала запроси код, затем пришли его командой.")

        config = self._require_login_prerequisites()
        pending_state = await self._load_pending_auth()
        if pending_state is None:
            raise ValueError(
                "Нет активного запроса кода. Сначала вызови /fullaccess_login без аргументов."
            )

        client = self.client_factory(config)
        password: str | None = None
        try:
            await client.complete_login(
                phone=pending_state.phone,
                code=normalized_code,
                phone_code_hash=pending_state.phone_code_hash,
                password=password,
            )
        except FullAccessPasswordRequiredError:
            if password_callback is None:
                return FullAccessLoginResult(
                    kind="password_required",
                    phone=pending_state.phone,
                    instructions=(
                        "Через бот пароль 2FA не принимаю.",
                        f"Заверши вход локально: python -m fullaccess.cli login --code {normalized_code}",
                    ),
                )
            password = password_callback().strip()
            if not password:
                raise ValueError("Пароль 2FA пустой. Локальный вход отменён.")
            await client.complete_login(
                phone=pending_state.phone,
                code=normalized_code,
                phone_code_hash=pending_state.phone_code_hash,
                password=password,
            )

        await self._clear_pending_auth()
        return FullAccessLoginResult(
            kind="authorized",
            phone=pending_state.phone,
        )

    async def logout(self) -> FullAccessLogoutResult:
        config = FullAccessConfig.from_settings(self.settings)
        pending_auth_cleared = await self._clear_pending_auth()

        if config.enabled and config.api_credentials_configured and self._transport_available():
            try:
                await self.client_factory(config).logout()
            except ValueError:
                pass

        session_removed = _delete_session_file(config.session_path)
        return FullAccessLogoutResult(
            session_removed=session_removed,
            pending_auth_cleared=pending_auth_cleared,
        )

    def _require_login_prerequisites(self) -> FullAccessConfig:
        config = FullAccessConfig.from_settings(self.settings)
        if not config.enabled:
            raise ValueError("Experimental full-access слой выключен. Включи FULLACCESS_ENABLED=true.")
        if not config.api_credentials_configured:
            raise ValueError(
                "Сначала задай FULLACCESS_API_ID и FULLACCESS_API_HASH."
            )
        if not self._transport_available():
            raise ValueError(
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'."
            )
        if not config.phone_configured:
            raise ValueError("Сначала задай FULLACCESS_PHONE для запроса кода.")
        return config

    async def _load_pending_auth(self) -> PendingAuthState | None:
        payload = await self.setting_repository.get_value(PENDING_AUTH_KEY)
        if not isinstance(payload, dict):
            return None

        phone = payload.get("phone")
        phone_code_hash = payload.get("phone_code_hash")
        requested_at = payload.get("requested_at")
        if not isinstance(phone, str) or not isinstance(phone_code_hash, str):
            return None

        timestamp = _parse_timestamp(requested_at)
        return PendingAuthState(
            phone=phone,
            phone_code_hash=phone_code_hash,
            requested_at=timestamp,
        )

    async def _clear_pending_auth(self) -> bool:
        existing = await self.setting_repository.get_by_key(PENDING_AUTH_KEY)
        await self.setting_repository.set_value(
            key=PENDING_AUTH_KEY,
            value_json=None,
            value_text=None,
        )
        return existing is not None

    def _transport_available(self) -> bool:
        if self.transport_available is not None:
            return self.transport_available
        if self.client_factory is not build_fullaccess_client:
            return True
        return telethon_is_available()


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(UTC)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return datetime.now(UTC)


def _delete_session_file(session_path: Path) -> bool:
    removed = False
    for candidate in (
        session_path,
        session_path.with_name(f"{session_path.name}-journal"),
    ):
        if not candidate.exists():
            continue
        candidate.unlink()
        removed = True
    return removed
