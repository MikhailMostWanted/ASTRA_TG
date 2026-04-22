import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatList } from "@/components/system/ChatList";
import type { ChatItem } from "@/lib/types";

const baseChat: ChatItem = {
  id: 42,
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
  lastTelegramMessageId: 9001,
  lastMessagePreview: "Когда сможешь прислать финальный файл?",
  lastDirection: "inbound",
  lastSourceAdapter: "fullaccess",
  lastSenderName: "Анна",
  avatarUrl: null,
  syncStatus: "fullaccess",
  memory: null,
  favorite: false,
};

describe("ChatList", () => {
  it("renders safely even with broken persisted favorites and workspace props", () => {
    render(
      <ChatList
        chats={[baseChat]}
        selectedChatId={42}
        search=""
        filter="all"
        sort="activity"
        favorites={null as unknown as number[]}
        workspaceStateByChat={null as unknown as Record<number, never>}
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
});
