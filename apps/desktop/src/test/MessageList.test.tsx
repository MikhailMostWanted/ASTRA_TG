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
  it("shows a soft runtime-only workspace notice when history is still legacy", () => {
    render(
      <MessageList
        chat={runtimeOnlyChat}
        messages={[]}
        loading={false}
        refreshing={false}
        fullaccessReady
        lastUpdatedAt="2026-04-22T11:01:00.000Z"
        freshness={null}
        errorMessage={null}
        onRefresh={vi.fn()}
        onSyncChat={vi.fn()}
      />,
    );

    expect(screen.getByText("new runtime")).toBeInTheDocument();
    expect(screen.getByText("2 непрочит.")).toBeInTheDocument();
    expect(screen.getByText("История пока остаётся на legacy")).toBeInTheDocument();
  });
});
