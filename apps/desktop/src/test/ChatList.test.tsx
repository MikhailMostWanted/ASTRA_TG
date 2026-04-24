import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatList } from "@/components/system/ChatList";
import type { ChatItem } from "@/lib/types";

const baseChat: ChatItem = {
  id: 42,
  localChatId: 42,
  runtimeChatId: -10042,
  chatKey: "telegram:-10042",
  workspaceAvailable: true,
  identity: {
    id: 42,
    localChatId: 42,
    runtimeChatId: -10042,
    chatKey: "telegram:-10042",
    workspaceAvailable: true,
  },
  telegramChatId: -10042,
  reference: "@product_team",
  title: "Команда продукта",
  handle: "product_team",
  type: "group",
  enabled: true,
  category: null,
  summarySchedule: null,
  replyAssistEnabled: true,
  autoReplyMode: null,
  excludeFromMemory: false,
  excludeFromDigest: false,
  isDigestTarget: false,
  messageCount: 18,
  lastMessageAt: "2026-04-22T10:30:00.000Z",
  lastMessageId: 300,
  lastMessageKey: "telegram:-10042:300",
  lastTelegramMessageId: 9001,
  lastMessagePreview: "Когда сможешь прислать финальный файл?",
  lastDirection: "inbound",
  lastSourceAdapter: "fullaccess",
  lastSenderName: "Анна",
  avatarUrl: null,
  syncStatus: "fullaccess",
  memory: null,
  favorite: false,
  rosterSource: "new",
  rosterLastActivityAt: "2026-04-22T10:30:00.000Z",
  rosterLastMessageKey: "telegram:-10042:300",
  rosterLastMessagePreview: "Когда сможешь прислать финальный файл?",
  rosterLastDirection: "inbound",
  rosterLastSenderName: "Анна",
  rosterFreshness: {
    mode: "fresh",
    label: "свежее",
    lastActivityAt: "2026-04-22T10:30:00.000Z",
  },
  unreadCount: 3,
  unreadMentionCount: 0,
  pinned: true,
  muted: false,
  archived: false,
  assetHints: {
    avatarCached: false,
    avatarSource: null,
  },
};

describe("ChatList", () => {
  it("renders safely even with broken persisted favorites and workspace props", () => {
    render(
      <ChatList
        chats={[baseChat]}
        selectedChatKey="telegram:-10042"
        search=""
        filter="all"
        sort="activity"
        favorites={null as unknown as number[]}
        workspaceStateByChat={null as unknown as Record<string, never>}
        loading={false}
        refreshing={false}
        refreshedAt="2026-04-22T10:31:00.000Z"
        onSearchChange={vi.fn()}
        onFilterChange={vi.fn()}
        onSortChange={vi.fn()}
        onSelectChat={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText("Команда продукта")).toBeInTheDocument();
    expect(screen.getByText("Нужен ответ")).toBeInTheDocument();
  });

  it("shows unavailable new runtime state without breaking the compact layout", () => {
    render(
      <ChatList
        chats={[baseChat]}
        selectedChatKey="telegram:-10042"
        search=""
        filter="all"
        sort="activity"
        favorites={[]}
        workspaceStateByChat={{}}
        loading={false}
        refreshing={false}
        refreshedAt="2026-04-22T10:31:00.000Z"
        roster={{
          source: "new",
          requestedBackend: "new",
          effectiveBackend: "new",
          degraded: true,
          degradedReason: "Новый runtime временно деградировал.",
          lastUpdatedAt: "2026-04-22T10:31:00.000Z",
          lastSuccessAt: "2026-04-22T10:30:00.000Z",
          lastError: "Telethon timeout",
          lastErrorAt: "2026-04-22T10:30:30.000Z",
          route: {
            surface: "chatRoster",
            requested: "new",
            effective: "new",
            targetAvailable: true,
            targetReady: false,
            status: "unavailable",
            reason: "not route-ready",
          },
        }}
        live={{
          scope: "roster",
          status: "refreshed",
          degraded: false,
          changedItemCount: 2,
        }}
        onSearchChange={vi.fn()}
        onFilterChange={vi.fn()}
        onSortChange={vi.fn()}
        onSelectChat={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getAllByText("runtime недоступен").length).toBeGreaterThan(0);
    expect(screen.getByText(/Что случилось:/)).toBeInTheDocument();
    expect(screen.getByText("Новый runtime временно деградировал.")).toBeInTheDocument();
    expect(screen.getByText("3 непрочит.")).toBeInTheDocument();
  });

  it("shows compact markers for chat mode, pending confirmation and degraded active chat", () => {
    render(
      <ChatList
        chats={[{ ...baseChat, autoReplyMode: "semi_auto" }]}
        selectedChatKey="telegram:-10042"
        search=""
        filter="all"
        sort="activity"
        favorites={[]}
        workspaceStateByChat={{
          "telegram:-10042": {
            seenMessageKey: "telegram:-10042:200",
            seenMessageId: 200,
            draftText: "Ок, вернусь с файлом.",
            draftSourceMessageKey: "telegram:-10042:300",
            draftSourceMessageId: 300,
            draftFocusLabel: "вопрос",
            draftScopeKey: "telegram:-10042:300::вопрос::direct_reply::Когда сможешь прислать финальный файл?",
            draftUpdatedAt: "2026-04-22T10:32:00.000Z",
            sentSourceMessageKey: null,
            sentSourceMessageId: null,
            sentAt: null,
          },
        }}
        loading={false}
        refreshing={false}
        activeWorkspaceStatus={{
          source: "new",
          requestedBackend: "new",
          effectiveBackend: "new",
          degraded: true,
          degradedReason: "Telegram runtime отвечает нестабильно.",
          syncTrigger: "runtime_poll",
          updatedNow: false,
          syncError: "timeout",
          lastUpdatedAt: null,
          lastSuccessAt: null,
          lastError: "timeout",
          lastErrorAt: null,
          availability: {
            workspaceAvailable: true,
            historyReadable: true,
            runtimeReadable: false,
            legacyWorkspaceAvailable: false,
            replyContextAvailable: true,
            sendAvailable: false,
            autopilotAvailable: true,
            canLoadOlder: false,
          },
          messageSource: {
            backend: "unavailable",
            chatKey: "telegram:-10042",
            runtimeChatId: -10042,
            localChatId: 42,
            oldestMessageKey: null,
            newestMessageKey: "telegram:-10042:300",
            oldestRuntimeMessageId: null,
            newestRuntimeMessageId: 300,
          },
        }}
        activeAutopilot={{
          masterEnabled: true,
          allowChannels: false,
          globalMode: "semi_auto",
          mode: "semi_auto",
          effectiveMode: "semi_auto",
          trusted: true,
          allowed: false,
          autopilotAllowed: false,
          writeReady: false,
          decision: {
            mode: "semi_auto",
            status: "awaiting_confirmation",
            action: "confirm",
            allowed: true,
            reason: "Ждёт подтверждение.",
            confidence: 0.91,
            trigger: "вопрос",
            sourceMessageId: 300,
            sourceMessageKey: "telegram:-10042:300",
            replyText: "Ок, вернусь с файлом.",
            pendingDraftStatus: "awaiting_confirmation",
          },
          pendingDraft: {
            id: "pending",
            text: "Ок, вернусь с файлом.",
            status: "awaiting_confirmation",
          },
          lastSentAt: null,
          lastSentSourceMessageId: null,
          cooldown: {
            active: false,
            remainingSeconds: 0,
            until: null,
          },
          journal: [],
        }}
        onSearchChange={vi.fn()}
        onFilterChange={vi.fn()}
        onSortChange={vi.fn()}
        onSelectChat={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getAllByText("Полуавтомат").length).toBeGreaterThan(0);
    expect(screen.getByText("Черновик")).toBeInTheDocument();
    expect(screen.getByText("Ждёт подтверждение")).toBeInTheDocument();
    expect(screen.getByText("Нестабильно")).toBeInTheDocument();
  });
});
