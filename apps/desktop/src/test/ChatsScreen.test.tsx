import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatsScreen } from "@/screens/ChatsScreen";
import type { ChatItem, ChatWorkspacePayload } from "@/lib/types";
import { useAppStore } from "@/stores/app-store";


const apiMock = vi.hoisted(() => ({
  chats: vi.fn(),
  fullaccess: vi.fn(),
  chatWorkspace: vi.fn(),
  chatMessages: vi.fn(),
  syncSource: vi.fn(),
  sendChatMessage: vi.fn(),
  updateAutopilotGlobal: vi.fn(),
  updateChatAutopilot: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMock,
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/system/ChatList", () => ({
  ChatList: ({ chats, selectedChatKey }: { chats: ChatItem[]; selectedChatKey: string | null }) => (
    <div data-testid="chat-list">
      {selectedChatKey}
      {chats.map((chat) => (
        <div key={chat.chatKey}>{chat.title}</div>
      ))}
    </div>
  ),
}));

vi.mock("@/components/system/MessageList", () => ({
  MessageList: ({
    chat,
    messages,
    workspaceStatus,
  }: {
    chat: ChatItem | null;
    messages: Array<{ text: string | null }>;
    workspaceStatus: { source?: string | null } | null;
  }) => (
    <div data-testid="message-list">
      <div>{chat?.chatKey || "no-chat"}</div>
      <div>{workspaceStatus?.source || "no-source"}</div>
      {messages.map((message, index) => (
        <div key={index}>{message.text}</div>
      ))}
    </div>
  ),
}));

vi.mock("@/components/system/ReplyPanel", () => ({
  ReplyPanel: ({
    reply,
    replyContext,
    workspaceStatus,
    sendStatus,
    sending,
    onSend,
  }: {
    reply: { kind?: string | null } | null;
    replyContext: { sourceMessageKey?: string | null; focusLabel?: string | null } | null;
    workspaceStatus: { source?: string | null } | null;
    sendStatus?: { message: string } | null;
    sending?: boolean;
    onSend?: (
      text: string,
      sourceMessageId: number | null,
      sourceMessageKey: string | null,
      draftScopeKey: string | null,
    ) => void;
  }) => (
    <div data-testid="reply-panel">
      <div>{reply?.kind || "no-reply"}</div>
      <div>{replyContext?.sourceMessageKey || "no-message-key"}</div>
      <div>{replyContext?.focusLabel || "no-focus"}</div>
      <div>{workspaceStatus?.source || "no-source"}</div>
      <div>{sendStatus?.message || "no-send-status"}</div>
      <div>{sending ? "sending" : "not-sending"}</div>
      <button
        type="button"
        onClick={() => onSend?.(
          "Отредактированный draft",
          null,
          replyContext?.sourceMessageKey ?? null,
          "telegram:-100777:41::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
        )}
      >
        test-send-draft
      </button>
    </div>
  ),
}));


const runtimeOnlyChat: ChatItem = {
  id: -200001,
  localChatId: null,
  runtimeChatId: -100777,
  chatKey: "telegram:-100777",
  workspaceAvailable: false,
  identity: {
    id: -200001,
    localChatId: null,
    runtimeChatId: -100777,
    chatKey: "telegram:-100777",
    workspaceAvailable: false,
  },
  telegramChatId: -100777,
  reference: "@runtime_chat",
  title: "Runtime chat",
  handle: "runtime_chat",
  type: "group",
  enabled: false,
  category: "runtime_only",
  summarySchedule: null,
  replyAssistEnabled: false,
  autoReplyMode: null,
  excludeFromMemory: false,
  excludeFromDigest: false,
  isDigestTarget: false,
  messageCount: 2,
  lastMessageAt: "2026-04-23T09:05:00.000Z",
  lastMessageId: null,
  lastMessageKey: "telegram:-100777:52",
  lastTelegramMessageId: 52,
  lastMessagePreview: "Да, смотрю это сейчас.",
  lastDirection: "outbound",
  lastSourceAdapter: "new_runtime",
  lastSenderName: "Михаил",
  avatarUrl: null,
  syncStatus: "runtime",
  memory: null,
  favorite: false,
  rosterSource: "new",
  rosterLastActivityAt: "2026-04-23T09:05:00.000Z",
  rosterLastMessageKey: "telegram:-100777:52",
  rosterLastMessagePreview: "Да, смотрю это сейчас.",
  rosterLastDirection: "outbound",
  rosterLastSenderName: "Михаил",
  rosterFreshness: {
    mode: "fresh",
    label: "свежее",
    lastActivityAt: "2026-04-23T09:05:00.000Z",
  },
  unreadCount: 4,
  unreadMentionCount: 1,
  pinned: true,
  muted: false,
  archived: false,
  assetHints: {
    avatarCached: false,
    avatarSource: null,
  },
};


describe("ChatsScreen", () => {
  beforeEach(() => {
    Object.values(apiMock).forEach((mockFn) => mockFn.mockReset());
    useAppStore.getState().resetDesktopState();
  });

  it("opens runtime-only chat and renders a unified new workspace snapshot", async () => {
    apiMock.chats.mockResolvedValue({
      items: [runtimeOnlyChat],
      count: 1,
      source: "new",
      roster: {
        source: "new",
        requestedBackend: "new",
        effectiveBackend: "new",
        degraded: false,
        degradedReason: null,
        lastUpdatedAt: "2026-04-23T09:05:02.000Z",
        lastSuccessAt: "2026-04-23T09:05:02.000Z",
        lastError: null,
        lastErrorAt: null,
        route: {
          surface: "chatRoster",
          requested: "new",
          effective: "new",
          targetAvailable: true,
          targetReady: true,
          reason: null,
        },
      },
      refreshedAt: "2026-04-23T09:05:02.000Z",
      filters: {
        active: "all",
        sort: "activity",
        search: "",
      },
    });
    apiMock.fullaccess.mockResolvedValue({
      status: {
        readyForManualSync: false,
        readyForManualSend: false,
      },
    });
    apiMock.chatWorkspace.mockResolvedValue(buildRuntimeOnlyWorkspacePayload());
    apiMock.chatMessages.mockResolvedValue({
      chat: runtimeOnlyChat,
      messages: [],
      history: {
        limit: 50,
        returnedCount: 0,
        hasMoreBefore: false,
        beforeRuntimeMessageId: null,
        oldestMessageKey: null,
        newestMessageKey: null,
        oldestRuntimeMessageId: null,
        newestRuntimeMessageId: null,
      },
      status: buildRuntimeOnlyWorkspacePayload().status,
      refreshedAt: "2026-04-23T09:05:02.000Z",
    });

    renderScreen();

    expect(await screen.findAllByText("Runtime chat")).not.toHaveLength(0);
    await waitFor(() => {
      expect(apiMock.chatWorkspace).toHaveBeenCalledWith(-200001, 60);
    });

    expect(screen.getByTestId("chat-list")).toHaveTextContent("telegram:-100777");
    expect(screen.getByTestId("message-list")).toHaveTextContent("telegram:-100777");
    expect(screen.getByTestId("message-list")).toHaveTextContent("new");
    expect(screen.getByTestId("message-list")).toHaveTextContent("Сможешь посмотреть это сегодня?");
    expect(screen.getByTestId("reply-panel")).toHaveTextContent("workspace_context_only");
    expect(screen.getByTestId("reply-panel")).toHaveTextContent("telegram:-100777:41");
    expect(screen.getByTestId("reply-panel")).toHaveTextContent("вопрос");
  });

  it("sends runtime-only draft once and refreshes workspace after success", async () => {
    const workspace = buildRuntimeOnlyWorkspacePayload({
      sendAvailable: true,
      replyKind: "suggestion",
    });
    const sentWorkspace = buildRuntimeOnlyWorkspacePayload({
      sendAvailable: true,
      replyKind: "workspace_context_only",
      extraMessageText: "Отредактированный draft",
    });
    apiMock.chats.mockResolvedValue({
      items: [runtimeOnlyChat],
      count: 1,
      source: "new",
      roster: {
        source: "new",
        requestedBackend: "new",
        effectiveBackend: "new",
        degraded: false,
        degradedReason: null,
        lastUpdatedAt: "2026-04-23T09:05:02.000Z",
        lastSuccessAt: "2026-04-23T09:05:02.000Z",
        lastError: null,
        lastErrorAt: null,
        route: {},
      },
      refreshedAt: "2026-04-23T09:05:02.000Z",
      filters: {
        active: "all",
        sort: "activity",
        search: "",
      },
    });
    apiMock.fullaccess.mockResolvedValue({
      status: {
        readyForManualSync: false,
        readyForManualSend: false,
      },
    });
    apiMock.chatWorkspace
      .mockResolvedValueOnce(workspace)
      .mockResolvedValue(sentWorkspace);
    apiMock.sendChatMessage.mockResolvedValue({
      ok: true,
      status: "success",
      reason: "Сообщение отправлено.",
      error: null,
      source: "new",
      requestedBackend: "new",
      effectiveBackend: "new",
      backend: "new",
      route: {},
      fallback: {
        used: false,
        reason: null,
      },
      target: {
        requestedChatId: -200001,
        localChatId: null,
        runtimeChatId: -100777,
        chatKey: "telegram:-100777",
      },
      sentMessage: sentWorkspace.messages[sentWorkspace.messages.length - 1],
      sentMessageIdentity: {
        messageKey: "telegram:-100777:53",
      },
      workspace: sentWorkspace,
      debug: {
        journal: {
          timestamp: "2026-04-23T09:06:00.000Z",
          chatKey: "telegram:-100777",
          runtimeChatId: -100777,
          localChatId: null,
          backend: "new",
          requestedBackend: "new",
          effectiveBackend: "new",
          draftScopeKey: "telegram:-100777:41::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
          success: true,
          status: "success",
          reason: "Сообщение отправлено.",
          errorReason: null,
          errorCode: null,
          sentMessageIdentity: {
            messageKey: "telegram:-100777:53",
          },
          route: {},
          fallback: {
            used: false,
            reason: null,
          },
        },
        trace: null,
      },
    });

    renderScreen();

    await screen.findAllByText("Runtime chat");
    await waitFor(() => {
      expect(apiMock.chatWorkspace).toHaveBeenCalledWith(-200001, 60);
    });

    fireEvent.click(screen.getByRole("button", { name: "test-send-draft" }));
    fireEvent.click(screen.getByRole("button", { name: "test-send-draft" }));

    await waitFor(() => {
      expect(apiMock.sendChatMessage).toHaveBeenCalledTimes(1);
    });
    expect(apiMock.sendChatMessage).toHaveBeenCalledWith(-200001, {
      text: "Отредактированный draft",
      source_message_id: null,
      reply_to_source_message_id: null,
      source_message_key: "telegram:-100777:41",
      reply_to_source_message_key: "telegram:-100777:41",
      draft_scope_key: "telegram:-100777:41::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
      client_send_id: expect.stringMatching(/^telegram:-100777:/),
    });
    expect(await screen.findByText("Отредактированный draft")).toBeInTheDocument();
    expect(screen.getByTestId("reply-panel")).toHaveTextContent("Сообщение отправлено.");
  });
});


function renderScreen() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ChatsScreen />
    </QueryClientProvider>,
  );
}


function buildRuntimeOnlyWorkspacePayload({
  sendAvailable = false,
  replyKind = "workspace_context_only",
  extraMessageText,
}: {
  sendAvailable?: boolean;
  replyKind?: string;
  extraMessageText?: string;
} = {}): ChatWorkspacePayload {
  const extraMessages = extraMessageText
    ? [
        {
          id: 53,
          chatKey: "telegram:-100777",
          messageKey: "telegram:-100777:53",
          runtimeMessageId: 53,
          localMessageId: null,
          telegramMessageId: 53,
          chatId: -200001,
          direction: "outbound",
          sourceAdapter: "new_runtime",
          sourceType: "message",
          senderId: 7,
          senderName: "Михаил",
          sentAt: "2026-04-23T09:06:00.000Z",
          text: extraMessageText,
          normalizedText: extraMessageText,
          replyToMessageId: null,
          replyToLocalMessageId: null,
          replyToRuntimeMessageId: 41,
          replyToMessageKey: "telegram:-100777:41",
          hasMedia: false,
          mediaType: null,
          mediaPreviewUrl: null,
          forwardInfo: null,
          entities: null,
          preview: extraMessageText,
        },
      ]
    : [];
  return {
    chat: runtimeOnlyChat,
    messages: [
      {
        id: 41,
        chatKey: "telegram:-100777",
        messageKey: "telegram:-100777:41",
        runtimeMessageId: 41,
        localMessageId: null,
        telegramMessageId: 41,
        chatId: -200001,
        direction: "inbound",
        sourceAdapter: "new_runtime",
        sourceType: "message",
        senderId: 11,
        senderName: "Анна",
        sentAt: "2026-04-23T09:04:00.000Z",
        text: "Сможешь посмотреть это сегодня?",
        normalizedText: "Сможешь посмотреть это сегодня?",
        replyToMessageId: null,
        replyToLocalMessageId: null,
        replyToRuntimeMessageId: null,
        replyToMessageKey: null,
        hasMedia: false,
        mediaType: null,
        mediaPreviewUrl: null,
        forwardInfo: null,
        entities: null,
        preview: "Сможешь посмотреть это сегодня?",
      },
      {
        id: 52,
        chatKey: "telegram:-100777",
        messageKey: "telegram:-100777:52",
        runtimeMessageId: 52,
        localMessageId: null,
        telegramMessageId: 52,
        chatId: -200001,
        direction: "outbound",
        sourceAdapter: "new_runtime",
        sourceType: "message",
        senderId: 7,
        senderName: "Михаил",
        sentAt: "2026-04-23T09:05:00.000Z",
        text: "Да, смотрю это сейчас.",
        normalizedText: "Да, смотрю это сейчас.",
        replyToMessageId: null,
        replyToLocalMessageId: null,
        replyToRuntimeMessageId: 41,
        replyToMessageKey: "telegram:-100777:41",
        hasMedia: false,
        mediaType: null,
        mediaPreviewUrl: null,
        forwardInfo: null,
        entities: null,
        preview: "Да, смотрю это сейчас.",
      },
      ...extraMessages,
    ],
    history: {
      limit: 60,
      returnedCount: 2,
      hasMoreBefore: true,
      beforeRuntimeMessageId: 41,
      oldestMessageKey: "telegram:-100777:41",
      newestMessageKey: "telegram:-100777:52",
      oldestRuntimeMessageId: 41,
      newestRuntimeMessageId: 52,
    },
    replyContext: {
      available: true,
      sourceBackend: "new",
      focusLabel: "вопрос",
      focusReason: "Последний входящий message остаётся без ответа.",
      replyOpportunityMode: "direct_reply",
      replyOpportunityReason: "Есть свежий незакрытый вопрос.",
      sourceMessageKey: "telegram:-100777:41",
      sourceRuntimeMessageId: 41,
      sourceLocalMessageId: null,
      sourceSenderName: "Анна",
      sourceMessagePreview: "Сможешь посмотреть это сегодня?",
      sourceSentAt: "2026-04-23T09:04:00.000Z",
      draftScopeBasis: {
        sourceMessageKey: "telegram:-100777:41",
        sourceMessageId: null,
        runtimeMessageId: 41,
        focusLabel: "вопрос",
        sourceMessagePreview: "Сможешь посмотреть это сегодня?",
        replyOpportunityMode: "direct_reply",
      },
      draftScopeKey: "telegram:-100777:41::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
    },
    reply: {
      kind: replyKind,
      chatId: null,
      chatTitle: "Runtime chat",
      chatReference: "@runtime_chat",
      errorMessage: "Reply generation на новом workspace пока не включена.",
      sourceSenderName: "Анна",
      sourceMessagePreview: "Сможешь посмотреть это сегодня?",
      suggestion: null,
      actions: {
        copy: false,
        refresh: true,
        pasteToTelegram: false,
        send: sendAvailable,
        markSent: false,
        variants: {},
        disabledReason: sendAvailable ? null : "Write-path на этом этапе выключен.",
      },
    },
    autopilot: null,
    freshness: {
      mode: "fresh",
      label: "Контекст из new runtime",
      detail: "Активный чат читается напрямую из нового Telegram runtime.",
      isStale: false,
      fullaccessReady: false,
      canManualSync: false,
      lastSyncAt: "2026-04-23T09:05:02.000Z",
      reference: "@runtime_chat",
      createdCount: 0,
      updatedCount: 0,
      skippedCount: 0,
      syncTrigger: "runtime_poll",
      updatedNow: true,
      syncError: null,
    },
    status: {
      source: "new",
      requestedBackend: "new",
      effectiveBackend: "new",
      degraded: false,
      degradedReason: null,
      syncTrigger: "runtime_poll",
      updatedNow: true,
      syncError: null,
      lastUpdatedAt: "2026-04-23T09:05:02.000Z",
      lastSuccessAt: "2026-04-23T09:05:02.000Z",
      lastError: null,
      lastErrorAt: null,
      availability: {
        workspaceAvailable: true,
        historyReadable: true,
        runtimeReadable: true,
        legacyWorkspaceAvailable: false,
        replyContextAvailable: true,
        sendAvailable,
        autopilotAvailable: false,
        canLoadOlder: true,
      },
      messageSource: {
        backend: "new_runtime",
        chatKey: "telegram:-100777",
        runtimeChatId: -100777,
        localChatId: null,
        oldestMessageKey: "telegram:-100777:41",
        newestMessageKey: "telegram:-100777:52",
        oldestRuntimeMessageId: 41,
        newestRuntimeMessageId: 52,
      },
      route: {
        surface: "messageWorkspace",
        requested: "new",
        effective: "new",
        targetAvailable: true,
        targetReady: true,
        reason: null,
      },
      sendPath: {
        surface: "sendPath",
        requested: "new",
        effective: sendAvailable ? "new" : "legacy",
        targetAvailable: true,
        targetReady: sendAvailable,
        reason: sendAvailable ? null : "not ready",
      },
      sendDisabledReason: sendAvailable ? null : "Write-path на этом этапе выключен.",
    },
    refreshedAt: "2026-04-23T09:05:02.000Z",
  };
}
