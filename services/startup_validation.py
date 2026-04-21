from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from services.bot_owner import BotOwnerService
from services.operational_state import OperationalStateService
from services.providers.manager import ProviderManager
from storage.repositories import MessageRepository, SettingRepository, SystemRepository
from worker.jobs import list_registered_jobs


@dataclass(frozen=True, slots=True)
class StartupCheck:
    key: str
    title: str
    ready: bool
    detail: str
    critical: bool = False


@dataclass(frozen=True, slots=True)
class StartupReport:
    app_name: str
    can_start: bool
    checks: tuple[StartupCheck, ...]
    warnings: tuple[str, ...]
    critical_issues: tuple[str, ...]


@dataclass(slots=True)
class StartupValidationService:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]

    async def build_bot_report(self) -> StartupReport:
        return await self._build_report("bot")

    async def build_worker_report(self) -> StartupReport:
        return await self._build_report("worker")

    async def store_report(self, report: StartupReport) -> None:
        async with self.session_factory() as session:
            await OperationalStateService(SettingRepository(session)).record_startup_report(
                report.app_name,
                can_start=report.can_start,
                warnings=report.warnings,
                critical_issues=report.critical_issues,
            )
            await session.commit()

    async def _build_report(self, app_name: str) -> StartupReport:
        checks: list[StartupCheck] = []
        warnings: list[str] = []
        critical_issues: list[str] = []

        checks.append(
            StartupCheck(
                key="telegram_bot_token",
                title="telegram token",
                ready=bool(self.settings.telegram_bot_token) or app_name == "worker",
                detail=(
                    "TELEGRAM_BOT_TOKEN задан."
                    if self.settings.telegram_bot_token
                    else (
                        "TELEGRAM_BOT_TOKEN не задан, worker продолжит работу без Telegram-доставки."
                        if app_name == "worker"
                        else "TELEGRAM_BOT_TOKEN не задан."
                    )
                ),
                critical=app_name == "bot",
            )
        )

        try:
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
                checks.append(
                    StartupCheck(
                        key="database",
                        title="database",
                        ready=True,
                        detail="База данных отвечает.",
                        critical=True,
                    )
                )

                schema_revision = await SystemRepository(session).get_schema_revision()
                schema_ready = schema_revision is not None
                checks.append(
                    StartupCheck(
                        key="schema_revision",
                        title="schema revision",
                        ready=schema_ready,
                        detail=(
                            f"Миграции применены: {schema_revision}."
                            if schema_ready
                            else "Миграции ещё не применены."
                        ),
                        critical=True,
                    )
                )

                owner_chat_id = await BotOwnerService(SettingRepository(session)).get_owner_chat_id()
                checks.append(
                    StartupCheck(
                        key="owner_chat",
                        title="owner chat",
                        ready=owner_chat_id is not None,
                        detail=(
                            f"owner chat сохранён: {owner_chat_id}."
                            if owner_chat_id is not None
                            else "owner chat пока неизвестен."
                        ),
                    )
                )

                provider_status = await ProviderManager.from_settings(
                    self.settings,
                    setting_repository=SettingRepository(session),
                ).get_status(check_api=False)
                checks.append(
                    StartupCheck(
                        key="provider_layer",
                        title="provider layer",
                        ready=(not provider_status.enabled) or provider_status.configured,
                        detail=(
                            "Provider layer выключен."
                            if not provider_status.enabled
                            else (
                                f"Provider layer готов: {provider_status.provider_name or 'provider'}."
                                if provider_status.configured
                                else f"Provider layer не готов: {provider_status.reason}"
                            )
                        ),
                    )
                )

                fullaccess_status = await FullAccessAuthService(
                    settings=self.settings,
                    setting_repository=SettingRepository(session),
                    message_repository=MessageRepository(session),
                ).build_status_report()
                checks.append(
                    StartupCheck(
                        key="fullaccess_layer",
                        title="full-access layer",
                        ready=(not fullaccess_status.enabled) or fullaccess_status.ready_for_manual_sync,
                        detail=(
                            "Experimental full-access выключен."
                            if not fullaccess_status.enabled
                            else (
                                "Experimental full-access готов."
                                if fullaccess_status.ready_for_manual_sync
                                else f"Experimental full-access не готов: {fullaccess_status.reason}"
                            )
                        ),
                    )
                )

                if app_name == "worker":
                    jobs = list_registered_jobs()
                    checks.append(
                        StartupCheck(
                            key="worker_jobs",
                            title="worker jobs",
                            ready=bool(jobs),
                            detail=(
                                f"Зарегистрированы worker jobs: {', '.join(jobs)}."
                                if jobs
                                else "Зарегистрированные worker jobs не найдены."
                            ),
                            critical=True,
                        )
                    )
        except SQLAlchemyError as error:
            checks.append(
                StartupCheck(
                    key="database",
                    title="database",
                    ready=False,
                    detail=f"База данных недоступна: {error}",
                    critical=True,
                )
            )

        for item in checks:
            if item.ready:
                continue
            if item.critical:
                critical_issues.append(item.detail)
            else:
                warnings.append(item.detail)

        return StartupReport(
            app_name=app_name,
            can_start=not critical_issues,
            checks=tuple(checks),
            warnings=tuple(warnings),
            critical_issues=tuple(critical_issues),
        )
