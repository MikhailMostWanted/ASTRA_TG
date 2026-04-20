from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.persona_rules import (
    DEFAULT_OWNER_PERSONA_CORE,
    DEFAULT_PERSONA_ENABLED,
    DEFAULT_PERSONA_GUARDRAILS,
    DEFAULT_PERSONA_VERSION,
    OwnerPersonaCore,
    PersonaGuardrailConfig,
)
from storage.repositories import SettingRepository


@dataclass(frozen=True, slots=True)
class PersonaState:
    enabled: bool
    version: str
    core: OwnerPersonaCore | None
    guardrails: PersonaGuardrailConfig | None
    source: str
    errors: tuple[str, ...] = ()

    @property
    def core_loaded(self) -> bool:
        return self.core is not None

    @property
    def guardrails_active(self) -> bool:
        return self.guardrails is not None and self.guardrails.active_checks_count > 0


@dataclass(frozen=True, slots=True)
class PersonaStatusReport:
    core_loaded: bool
    active_core_rules: int
    reply_enrichment_enabled: bool
    active_guardrail_checks: int
    anti_pattern_rules: tuple[str, ...]
    version: str
    source: str


@dataclass(slots=True)
class PersonaCoreService:
    setting_repository: SettingRepository

    async def load_state(self) -> PersonaState:
        core_payload = await self.setting_repository.get_value("persona.core")
        guardrail_payload = await self.setting_repository.get_value("persona.guardrails")
        enabled_payload = await self.setting_repository.get_value("persona.enabled")
        version_payload = await self.setting_repository.get_value("persona.version")

        source = "settings"
        errors: list[str] = []

        if core_payload is None:
            core_payload = DEFAULT_OWNER_PERSONA_CORE
            source = "builtin_seed"
        if guardrail_payload is None:
            guardrail_payload = DEFAULT_PERSONA_GUARDRAILS
            source = "builtin_seed"

        try:
            core = OwnerPersonaCore.from_payload(core_payload)
        except ValueError as error:
            errors.append(str(error))
            core = OwnerPersonaCore.from_payload(DEFAULT_OWNER_PERSONA_CORE)
            source = "builtin_fallback"

        try:
            guardrails = PersonaGuardrailConfig.from_payload(guardrail_payload)
        except ValueError as error:
            errors.append(str(error))
            guardrails = PersonaGuardrailConfig.from_payload(DEFAULT_PERSONA_GUARDRAILS)
            source = "builtin_fallback"

        return PersonaState(
            enabled=_parse_enabled(enabled_payload),
            version=_parse_version(version_payload),
            core=core,
            guardrails=guardrails,
            source=source,
            errors=tuple(errors),
        )

    async def build_status_report(self) -> PersonaStatusReport:
        state = await self.load_state()
        core = state.core
        guardrails = state.guardrails
        return PersonaStatusReport(
            core_loaded=state.core_loaded,
            active_core_rules=core.active_rule_count if core is not None else 0,
            reply_enrichment_enabled=state.enabled and state.core_loaded,
            active_guardrail_checks=(
                guardrails.active_checks_count
                if guardrails is not None
                else 0
            ),
            anti_pattern_rules=(
                core.anti_pattern_rules
                if core is not None
                else ()
            ),
            version=state.version,
            source=state.source,
        )


def _parse_enabled(value: Any) -> bool:
    if value is None:
        return bool(DEFAULT_PERSONA_ENABLED.get("enabled", True))
    if isinstance(value, dict):
        return bool(value.get("enabled", True))
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no", "disabled"}
    return bool(value)


def _parse_version(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict) and isinstance(value.get("version"), str):
        version = str(value["version"]).strip()
        if version:
            return version
    return DEFAULT_PERSONA_VERSION
