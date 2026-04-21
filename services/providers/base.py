from __future__ import annotations

from abc import ABC, abstractmethod

from services.providers.models import (
    AnalyzeContextRequest,
    DigestImproveRequest,
    DigestImprovementCandidate,
    ReplyRefinementCandidate,
    RewriteReplyRequest,
    SummarizeMessagesRequest,
)


class BaseProvider(ABC):
    name: str

    @abstractmethod
    async def check_health(self) -> tuple[bool, str]:
        raise NotImplementedError

    @abstractmethod
    async def rewrite_reply(
        self,
        request: RewriteReplyRequest,
    ) -> ReplyRefinementCandidate:
        raise NotImplementedError

    @abstractmethod
    async def improve_digest(
        self,
        request: DigestImproveRequest,
    ) -> DigestImprovementCandidate:
        raise NotImplementedError

    async def summarize_messages(self, request: SummarizeMessagesRequest):
        raise NotImplementedError(f"{self.name} пока не реализует summarize_messages")

    async def analyze_context(self, request: AnalyzeContextRequest):
        raise NotImplementedError(f"{self.name} пока не реализует analyze_context")
