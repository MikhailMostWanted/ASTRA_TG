from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models import Chat, StyleProfile
from storage.repositories import ChatRepository, ChatStyleOverrideRepository, StyleProfileRepository


@dataclass(frozen=True, slots=True)
class StyleProfileSnapshot:
    id: int
    key: str
    title: str
    description: str
    sort_order: int
    message_mode: str
    target_message_count: int
    max_message_count: int
    avg_length_hint: str
    punctuation_level: str
    profanity_level: str
    warmth_level: str
    directness_level: str
    explanation_pattern: tuple[str, ...]
    preferred_openers: tuple[str, ...]
    preferred_closers: tuple[str, ...]
    avoid_patterns: tuple[str, ...]
    casing_mode: str
    rhythm_mode: str

    @classmethod
    def from_model(cls, profile: StyleProfile) -> StyleProfileSnapshot:
        traits = profile.traits_json if isinstance(profile.traits_json, dict) else {}
        return cls(
            id=profile.id,
            key=profile.key,
            title=profile.title,
            description=profile.description,
            sort_order=profile.sort_order,
            message_mode=str(traits.get("message_mode") or "series"),
            target_message_count=max(1, int(traits.get("target_message_count") or 1)),
            max_message_count=max(1, int(traits.get("max_message_count") or 1)),
            avg_length_hint=str(traits.get("avg_length_hint") or "short"),
            punctuation_level=str(traits.get("punctuation_level") or "low"),
            profanity_level=str(traits.get("profanity_level") or "none"),
            warmth_level=str(traits.get("warmth_level") or "medium"),
            directness_level=str(traits.get("directness_level") or "medium"),
            explanation_pattern=_as_tuple(traits.get("explanation_pattern")),
            preferred_openers=_as_tuple(traits.get("preferred_openers")),
            preferred_closers=_as_tuple(traits.get("preferred_closers")),
            avoid_patterns=_as_tuple(traits.get("avoid_patterns")),
            casing_mode=str(traits.get("casing_mode") or "mostly_lower"),
            rhythm_mode=str(traits.get("rhythm_mode") or "telegram_bursts"),
        )


@dataclass(frozen=True, slots=True)
class StyleSelection:
    profile: StyleProfileSnapshot
    source: str
    source_reason: str
    override_profile_key: str | None


@dataclass(frozen=True, slots=True)
class StyleStatusReport:
    chat_title: str
    chat_reference: str
    selection: StyleSelection
    note: str | None = None


@dataclass(slots=True)
class StyleProfileService:
    chat_repository: ChatRepository
    style_profile_repository: StyleProfileRepository
    chat_style_override_repository: ChatStyleOverrideRepository
    selector: object

    async def list_profiles(self) -> tuple[StyleProfileSnapshot, ...]:
        profiles = await self.style_profile_repository.list_profiles()
        return tuple(StyleProfileSnapshot.from_model(profile) for profile in profiles)

    async def build_style_status(self, reference: str) -> StyleStatusReport:
        chat = await self._get_registered_chat(reference)
        selection = await self.selector.select_for_chat(chat)
        return StyleStatusReport(
            chat_title=chat.title,
            chat_reference=_build_chat_reference(chat),
            selection=selection,
        )

    async def set_chat_override(
        self,
        *,
        reference: str,
        profile_key: str,
    ) -> StyleStatusReport:
        chat = await self._get_registered_chat(reference)
        profile = await self.style_profile_repository.get_by_key(profile_key)
        if profile is None:
            raise ValueError(
                "Стиль-профиль не найден. Посмотри список через /style_profiles."
            )

        await self.chat_style_override_repository.set_override(
            chat_id=chat.id,
            style_profile_id=profile.id,
        )
        selection = await self.selector.select_for_chat(chat)
        return StyleStatusReport(
            chat_title=chat.title,
            chat_reference=_build_chat_reference(chat),
            selection=selection,
            note=f"Ручной override: {profile.key}",
        )

    async def unset_chat_override(self, *, reference: str) -> StyleStatusReport:
        chat = await self._get_registered_chat(reference)
        await self.chat_style_override_repository.unset_override(chat_id=chat.id)
        selection = await self.selector.select_for_chat(chat)
        return StyleStatusReport(
            chat_title=chat.title,
            chat_reference=_build_chat_reference(chat),
            selection=selection,
            note="Ручной override снят.",
        )

    async def _get_registered_chat(self, reference: str) -> Chat:
        chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference)
        if chat is None:
            raise ValueError(
                "Чат не зарегистрирован в allowlist. "
                "Сначала добавь его как источник через /source_add <chat_id|@username>."
            )
        return chat


def _build_chat_reference(chat: Chat) -> str:
    if getattr(chat, "handle", None):
        return f"@{chat.handle}"
    return str(chat.telegram_chat_id)


def _as_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
