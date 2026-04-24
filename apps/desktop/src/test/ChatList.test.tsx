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

  it("shows roster source and fallback state without breaking the compact layout", () => {
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
          source: "fallback_to_legacy",
          requestedBackend: "new",
          effectiveBackend: "legacy",
          degraded: true,
          degradedReason: "Новый runtime временно деградировал, поэтому roster обслуживается legacy.",
          lastUpdatedAt: "2026-04-22T10:31:00.000Z",
          lastSuccessAt: "2026-04-22T10:30:00.000Z",
          lastError: "Telethon timeout",
          lastErrorAt: "2026-04-22T10:30:30.000Z",
          route: {
            surface: "chatRoster",
            requested: "new",
            effective: "legacy",
            targetAvailable: true,
            targetReady: false,
            reason: "legacy remains effective",
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

    expect(screen.getByText("fallback на legacy")).toBeInTheDocument();
    expect(screen.getByText("fallback")).toBeInTheDocument();
    expect(screen.getByText("roster live +2")).toBeInTheDocument();
    expect(screen.getByText("Новый runtime временно деградировал, поэтому roster обслуживается legacy.")).toBeInTheDocument();
    expect(screen.getByText("3 непрочит.")).toBeInTheDocument();
  });
});
