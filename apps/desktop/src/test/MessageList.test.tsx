import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageList } from "@/components/system/MessageList";
import type { ChatItem } from "@/lib/types";


const runtimeOnlyChat: ChatItem = {
  id: -200001,
  localChatId: null,
  runtimeChatId: -100500,
  chatKey: "telegram:-100500",
  workspaceAvailable: false,
  identity: {
    id: -200001,
    localChatId: null,
    runtimeChatId: -100500,
    chatKey: "telegram:-100500",
    workspaceAvailable: false,
  },
  telegramChatId: -100500,
  reference: "-100500",
  title: "Новый runtime чат",
  handle: null,
  type: "group",
  enabled: false,
  category: "runtime_only",
  summarySchedule: null,
  replyAssistEnabled: false,
  autoReplyMode: null,
  excludeFromMemory: false,
  excludeFromDigest: false,
  isDigestTarget: false,
  messageCount: 0,
  lastMessageAt: null,
  lastMessageId: null,
  lastMessageKey: null,
  lastTelegramMessageId: null,
  lastMessagePreview: "Сообщений пока нет",
  lastDirection: null,
  lastSourceAdapter: null,
  lastSenderName: null,
  avatarUrl: null,
  syncStatus: "empty",
  memory: null,
  favorite: false,
  rosterSource: "new",
  rosterLastActivityAt: "2026-04-22T11:00:00.000Z",
  rosterLastMessageKey: null,
  rosterLastMessagePreview: "Новый runtime только что увидел этот чат.",
  rosterLastDirection: "inbound",
  rosterLastSenderName: "Анна",
  rosterFreshness: {
    mode: "fresh",
    label: "свежее",
    lastActivityAt: "2026-04-22T11:00:00.000Z",
  },
  unreadCount: 2,
  unreadMentionCount: 0,
  pinned: false,
  muted: false,
  archived: false,
  assetHints: {
    avatarCached: false,
    avatarSource: null,
  },
};


describe("MessageList", () => {
  it("shows workspace backend and unavailable state for runtime-only chat", () => {
    render(
      <MessageList
        chat={runtimeOnlyChat}
        messages={[]}
        loading={false}
        refreshing={false}
        fullaccessReady
        workspaceStatus={{
          source: "new",
          requestedBackend: "new",
          effectiveBackend: "new",
          degraded: false,
          degradedReason: null,
          syncTrigger: "runtime_poll",
          updatedNow: true,
          syncError: null,
          lastUpdatedAt: "2026-04-22T11:01:00.000Z",
          lastSuccessAt: "2026-04-22T11:01:00.000Z",
          lastError: null,
          lastErrorAt: null,
          availability: {
            workspaceAvailable: false,
            historyReadable: false,
            runtimeReadable: true,
            legacyWorkspaceAvailable: false,
            replyContextAvailable: false,
            sendAvailable: false,
            autopilotAvailable: false,
            canLoadOlder: false,
          },
          messageSource: {
            backend: "new_runtime",
            chatKey: "telegram:-100500",
            runtimeChatId: -100500,
            localChatId: null,
            oldestMessageKey: null,
            newestMessageKey: null,
            oldestRuntimeMessageId: null,
            newestRuntimeMessageId: null,
          },
          route: {},
        }}
        canLoadOlder={false}
        loadingOlder={false}
        lastUpdatedAt="2026-04-22T11:01:00.000Z"
        freshness={null}
        live={{
          scope: "active_chat",
          status: "paused",
          paused: true,
          degraded: true,
          newMessageCount: 2,
          meaningfulMessageCount: 1,
          lastError: "runtime timeout",
        }}
        errorMessage={null}
        onLoadOlder={vi.fn()}
        onRefresh={vi.fn()}
        onToggleLivePause={vi.fn()}
        onClearLiveError={vi.fn()}
        onSyncChat={vi.fn()}
      />,
    );

    expect(screen.getByText("чат пока недоступен")).toBeInTheDocument();
    expect(screen.getByText("live на паузе")).toBeInTheDocument();
    expect(screen.getAllByText("связь с Telegram нестабильна").length).toBeGreaterThan(0);
    expect(screen.getByText("runtime timeout")).toBeInTheDocument();
    expect(screen.getByText("Сбросить ошибку")).toBeInTheDocument();
    expect(screen.getByText("2 непрочит.")).toBeInTheDocument();
    expect(screen.getByText("Чат пока нельзя прочитать")).toBeInTheDocument();
  });

  it("highlights the source message and keeps the chat-like bubble grouping", () => {
    render(
      <MessageList
        chat={{ ...runtimeOnlyChat, messageCount: 3, unreadCount: 0 }}
        messages={[
          {
            id: 41,
            chatKey: "telegram:-100500",
            messageKey: "telegram:-100500:41",
            runtimeMessageId: 41,
            localMessageId: null,
            telegramMessageId: 41,
            chatId: -200001,
            direction: "inbound",
            sourceAdapter: "new_runtime",
            sourceType: "message",
            senderId: 11,
            senderName: "Анна",
            sentAt: "2026-04-22T11:01:00.000Z",
            text: "Сможешь посмотреть сегодня?",
            normalizedText: "Сможешь посмотреть сегодня?",
            replyToMessageId: null,
            replyToLocalMessageId: null,
            replyToRuntimeMessageId: null,
            replyToMessageKey: null,
            hasMedia: false,
            mediaType: null,
            mediaPreviewUrl: null,
            forwardInfo: null,
            entities: null,
            preview: "Сможешь посмотреть сегодня?",
          },
          {
            id: 42,
            chatKey: "telegram:-100500",
            messageKey: "telegram:-100500:42",
            runtimeMessageId: 42,
            localMessageId: null,
            telegramMessageId: 42,
            chatId: -200001,
            direction: "outbound",
            sourceAdapter: "new_runtime",
            sourceType: "message",
            senderId: 7,
            senderName: "Михаил",
            sentAt: "2026-04-22T11:02:00.000Z",
            text: "Да, посмотрю.",
            normalizedText: "Да, посмотрю.",
            replyToMessageId: null,
            replyToLocalMessageId: null,
            replyToRuntimeMessageId: 41,
            replyToMessageKey: "telegram:-100500:41",
            hasMedia: false,
            mediaType: null,
            mediaPreviewUrl: null,
            forwardInfo: null,
            entities: null,
            preview: "Да, посмотрю.",
          },
        ]}
        loading={false}
        refreshing={false}
        fullaccessReady
        workspaceStatus={{
          source: "new",
          requestedBackend: "new",
          effectiveBackend: "new",
          degraded: false,
          degradedReason: null,
          syncTrigger: "runtime_poll",
          updatedNow: true,
          syncError: null,
          lastUpdatedAt: "2026-04-22T11:03:00.000Z",
          lastSuccessAt: "2026-04-22T11:03:00.000Z",
          lastError: null,
          lastErrorAt: null,
          availability: {
            workspaceAvailable: true,
            historyReadable: true,
            runtimeReadable: true,
            legacyWorkspaceAvailable: false,
            replyContextAvailable: true,
            sendAvailable: true,
            autopilotAvailable: true,
            canLoadOlder: false,
          },
          messageSource: {
            backend: "new_runtime",
            chatKey: "telegram:-100500",
            runtimeChatId: -100500,
            localChatId: null,
            oldestMessageKey: "telegram:-100500:41",
            newestMessageKey: "telegram:-100500:42",
            oldestRuntimeMessageId: 41,
            newestRuntimeMessageId: 42,
          },
          route: {},
        }}
        highlightMessageKey="telegram:-100500:41"
        canLoadOlder={false}
        loadingOlder={false}
        lastUpdatedAt="2026-04-22T11:03:00.000Z"
        freshness={{
          mode: "fresh",
          label: "Контекст свежий",
          detail: "Хвост обновлён.",
          isStale: false,
          fullaccessReady: true,
          canManualSync: true,
          lastSyncAt: "2026-04-22T11:03:00.000Z",
          reference: "@runtime_chat",
          createdCount: 0,
          updatedCount: 0,
          skippedCount: 0,
          syncTrigger: "runtime_poll",
          updatedNow: true,
          syncError: null,
        }}
        live={{
          scope: "active_chat",
          status: "refreshed",
          paused: false,
          degraded: false,
          newMessageCount: 0,
          meaningfulMessageCount: 0,
        }}
        errorMessage={null}
        onLoadOlder={vi.fn()}
        onRefresh={vi.fn()}
        onToggleLivePause={vi.fn()}
        onClearLiveError={vi.fn()}
        onSyncChat={vi.fn()}
      />,
    );

    expect(screen.getByText("Анна")).toBeInTheDocument();
    expect(screen.getAllByText("Я").length).toBeGreaterThan(0);
    expect(screen.getByText("опорный сигнал")).toBeInTheDocument();
    expect(screen.getByText("Сможешь посмотреть сегодня?")).toBeInTheDocument();
  });
});
