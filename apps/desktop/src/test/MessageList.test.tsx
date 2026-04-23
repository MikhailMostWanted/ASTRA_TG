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
        errorMessage={null}
        onLoadOlder={vi.fn()}
        onRefresh={vi.fn()}
        onSyncChat={vi.fn()}
      />,
    );

    expect(screen.getByText("new workspace")).toBeInTheDocument();
    expect(screen.getByText("2 непрочит.")).toBeInTheDocument();
    expect(screen.getByText("Workspace для чтения пока недоступен")).toBeInTheDocument();
  });
});
