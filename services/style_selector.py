from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from models import Chat, ChatMemory, PersonMemory
from services.style_profiles import StyleProfileSnapshot, StyleSelection
from storage.repositories import (
    ChatMemoryRepository,
    ChatStyleOverrideRepository,
    PersonMemoryRepository,
    StyleProfileRepository,
)


ROMANTIC_KEYWORDS = (
    "романтичес",
    "нежн",
    "люблю",
    "обнима",
    "поцел",
    "скучаю",
    "мягкий личный",
)
EXPLAIN_KEYWORDS = (
    "объяс",
    "по шаг",
    "упрост",
    "разлож",
    "поясн",
    "разбер",
    "часто задаёт вопросы",
    "ждёт апдейт",
    "открытые хвосты",
)
HARD_FRIEND_KEYWORDS = (
    "жестк",
    "жёстк",
    "стеб",
    "подкол",
    "мат",
    "резкий дружеский",
)


@dataclass(slots=True)
class StyleSelectorService:
    style_profile_repository: StyleProfileRepository
    chat_style_override_repository: ChatStyleOverrideRepository
    chat_memory_repository: ChatMemoryRepository
    person_memory_repository: PersonMemoryRepository

    async def select_for_context(self, context) -> StyleSelection:
        return await self.select_for_chat(
            context.chat,
            chat_memory=context.chat_memory,
            person_memory=context.person_memory,
            linked_people=context.linked_people,
        )

    async def select_for_chat(
        self,
        chat: Chat,
        *,
        chat_memory: ChatMemory | None = None,
        person_memory: PersonMemory | None = None,
        linked_people: Sequence[PersonMemory] | None = None,
    ) -> StyleSelection:
        override = await self.chat_style_override_repository.get_override_for_chat(chat.id)
        if override is not None and override.style_profile is not None:
            return StyleSelection(
                profile=StyleProfileSnapshot.from_model(override.style_profile),
                source="override",
                source_reason="Ручной override для этого чата.",
                override_profile_key=override.style_profile.key,
            )

        if chat_memory is None:
            chat_memory = await self.chat_memory_repository.get_chat_memory(chat.id)
        if linked_people is None:
            linked_people = await self._load_linked_people(chat_memory)

        profile_key, reason = self._choose_fallback_profile_key(
            chat=chat,
            chat_memory=chat_memory,
            person_memory=person_memory,
            linked_people=linked_people,
        )
        profile = await self.style_profile_repository.get_by_key(profile_key)
        if profile is None and profile_key != "base":
            profile = await self.style_profile_repository.get_by_key("base")
            reason = "Нужный fallback-профиль не найден, использую базовый."
        if profile is None:
            raise RuntimeError("Встроенные style-профили не загружены в базу данных.")

        return StyleSelection(
            profile=StyleProfileSnapshot.from_model(profile),
            source="fallback",
            source_reason=reason,
            override_profile_key=None,
        )

    async def _load_linked_people(
        self,
        chat_memory: ChatMemory | None,
    ) -> tuple[PersonMemory, ...]:
        person_keys = [
            str(item.get("person_key"))
            for item in ((getattr(chat_memory, "linked_people_json", None) or []))
            if isinstance(item, dict) and item.get("person_key")
        ]
        linked_people = await self.person_memory_repository.get_people_memory_by_keys(person_keys)
        return tuple(linked_people)

    def _choose_fallback_profile_key(
        self,
        *,
        chat: Chat,
        chat_memory: ChatMemory | None,
        person_memory: PersonMemory | None,
        linked_people: Sequence[PersonMemory],
    ) -> tuple[str, str]:
        text_blob = "\n".join(
            fragment.casefold()
            for fragment in self._collect_text_fragments(
                chat_memory=chat_memory,
                person_memory=person_memory,
                linked_people=linked_people,
            )
            if fragment
        )

        if chat.type == "private" and _contains_any(text_blob, ROMANTIC_KEYWORDS):
            return "romantic_soft", "В памяти есть явные романтические сигналы."
        if _contains_any(text_blob, EXPLAIN_KEYWORDS):
            return "friend_explain", "В памяти есть явный объясняющий паттерн."
        if _contains_any(text_blob, HARD_FRIEND_KEYWORDS):
            return "friend_hard", "В памяти есть явный жёсткий дружеский паттерн."
        return "base", "Явных сигналов под другой профиль нет, использую базовый fallback."

    def _collect_text_fragments(
        self,
        *,
        chat_memory: ChatMemory | None,
        person_memory: PersonMemory | None,
        linked_people: Sequence[PersonMemory],
    ) -> tuple[str, ...]:
        fragments: list[str] = []
        for candidate in (
            getattr(chat_memory, "chat_summary_short", None),
            getattr(chat_memory, "chat_summary_long", None),
            getattr(chat_memory, "current_state", None),
            getattr(person_memory, "last_summary", None),
            getattr(person_memory, "interaction_pattern", None),
        ):
            if isinstance(candidate, str) and candidate.strip():
                fragments.append(candidate.strip())

        for person in linked_people:
            for candidate in (person.last_summary, person.interaction_pattern):
                if isinstance(candidate, str) and candidate.strip():
                    fragments.append(candidate.strip())
        return tuple(fragments)


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)
