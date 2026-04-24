import { startTransition, useDeferredValue, useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ChatList } from "@/components/system/ChatList";
import { MessageList } from "@/components/system/MessageList";
import { ReplyPanel } from "@/components/system/ReplyPanel";
import { WarningState } from "@/components/system/WarningState";
import { api } from "@/lib/api";
import {
  extractErrorMessage,
  normalizeReplyContextPayload,
  normalizeWorkspaceStatusPayload,
  safeArray,
} from "@/lib/runtime-guards";
import type { ChatSendPayload, MessageItem } from "@/lib/types";
import { useAppStore } from "@/stores/app-store";

const CHAT_POLL_MS = 6_000;
const FULLACCESS_WORKSPACE_POLL_MS = 5_000;
const LOCAL_WORKSPACE_POLL_MS = 7_000;

export function ChatsScreen() {
  const queryClient = useQueryClient();
  const rawSelectedChatKey = useAppStore((state) => state.selectedChatKey);
  const setSelectedChatKey = useAppStore((state) => state.setSelectedChatKey);
  const rawFavoriteChatIds = useAppStore((state) => state.favoriteChatIds);
  const toggleFavoriteChat = useAppStore((state) => state.toggleFavoriteChat);
  const rawChatWorkspace = useAppStore((state) => state.chatWorkspace);
  const markChatSeen = useAppStore((state) => state.markChatSeen);
  const saveReplyDraft = useAppStore((state) => state.saveReplyDraft);
  const markReplySent = useAppStore((state) => state.markReplySent);
  const clearReplyDraft = useAppStore((state) => state.clearReplyDraft);
  const selectedChatKey = typeof rawSelectedChatKey === "string" && rawSelectedChatKey.trim()
    ? rawSelectedChatKey
    : null;
  const favoriteChatIds = safeArray(rawFavoriteChatIds).filter(
    (item): item is number => typeof item === "number" && Number.isFinite(item),
  );
  const chatWorkspace =
    rawChatWorkspace && typeof rawChatWorkspace === "object" && !Array.isArray(rawChatWorkspace)
      ? rawChatWorkspace
      : {};

  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("activity");
  const deferredSearch = useDeferredValue(search);
  const lastWorkspaceSyncAtRef = useRef<string | null>(null);
  const sendInFlightRef = useRef(false);
  const [olderMessages, setOlderMessages] = useState<MessageItem[]>([]);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [manualSendStatus, setManualSendStatus] = useState<{
    status: string;
    message: string;
    backend: string | null;
    sentMessageKey: string | null;
    timestamp: string;
    tone: "success" | "error" | "pending" | "warning";
  } | null>(null);

  const chatsQuery = useQuery({
    queryKey: ["chats", deferredSearch, filter, sort],
    queryFn: () =>
      api.chats({
        search: deferredSearch,
        filter,
        sort,
      }),
    refetchInterval: CHAT_POLL_MS,
  });

  const fullaccessQuery = useQuery({
    queryKey: ["fullaccess"],
    queryFn: api.fullaccess,
    refetchInterval: 15_000,
  });
  const chatItems = safeArray(chatsQuery.data?.items);
  const rosterState = chatsQuery.data?.roster ?? null;

  useEffect(() => {
    if (chatItems.length === 0) {
      if (selectedChatKey !== null) {
        startTransition(() => setSelectedChatKey(null));
      }
      return;
    }

    const stillExists = chatItems.some((item) => item.chatKey === selectedChatKey);
    if (!stillExists) {
      startTransition(() => setSelectedChatKey(chatItems[0]?.chatKey ?? null));
    }
  }, [chatItems, selectedChatKey, setSelectedChatKey]);

  useEffect(() => {
    lastWorkspaceSyncAtRef.current = null;
    sendInFlightRef.current = false;
    setManualSendStatus(null);
    setOlderMessages([]);
  }, [selectedChatKey]);

  const selectedChat = chatItems.find((item) => item.chatKey === selectedChatKey) || null;
  const selectedLocalChatId = selectedChat?.localChatId ?? null;
  const selectedChatWorkspace = selectedChat?.chatKey ? chatWorkspace[selectedChat.chatKey] || null : null;
  const fullaccessReady = Boolean(fullaccessQuery.data?.status.readyForManualSync);

  const workspaceQuery = useQuery({
    queryKey: ["chat-workspace", selectedChat?.chatKey],
    queryFn: () => {
      if (!selectedChat) {
        throw new Error("Активный чат не выбран.");
      }
      return api.chatWorkspace(selectedChat.id, 60);
    },
    enabled: selectedChat !== null,
    refetchInterval:
      selectedChat?.syncStatus === "fullaccess"
        ? FULLACCESS_WORKSPACE_POLL_MS
        : LOCAL_WORKSPACE_POLL_MS,
  });

  const syncChatMutation = useMutation({
    mutationFn: ({
      chatId,
      chatKey: _chatKey,
      chatTitle,
      silent = false,
    }: {
      chatId: number;
      chatKey: string;
      chatTitle: string;
      silent?: boolean;
      trigger?: "manual" | "auto";
    }) => api.syncSource(chatId).then((payload) => ({ payload, chatTitle, silent })),
    onSuccess: async ({ payload, chatTitle, silent }, variables) => {
      if (!silent) {
        toast.success(
          `Чат «${chatTitle}» синхронизирован: +${payload.createdCount}, обновлено ${payload.updatedCount}.`,
        );
      }
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["chats"], type: "active" }),
        queryClient.refetchQueries({ queryKey: ["chat-workspace", variables.chatKey], exact: true }),
        queryClient.refetchQueries({ queryKey: ["fullaccess"], type: "active" }),
      ]);
    },
    onError: (error, variables) => {
      if (variables.trigger !== "auto") {
        toast.error(error instanceof Error ? error.message : "Не удалось синхронизировать выбранный чат.");
      }
    },
  });
  const sendMessageMutation = useMutation({
    mutationFn: ({
      chatId,
      chatKey: _chatKey,
      text,
      sourceMessageId,
      sourceMessageKey,
      draftScopeKey,
      clientSendId,
    }: {
      chatId: number;
      chatKey: string;
      text: string;
      sourceMessageId: number | null;
      sourceMessageKey: string | null;
      draftScopeKey: string | null;
      clientSendId: string;
    }) =>
      api.sendChatMessage(chatId, {
        text,
        source_message_id: sourceMessageId,
        reply_to_source_message_id: sourceMessageId,
        source_message_key: sourceMessageKey,
        reply_to_source_message_key: sourceMessageKey,
        draft_scope_key: draftScopeKey,
        client_send_id: clientSendId,
      }),
    onSuccess: async (payload, variables) => {
      if (!payload.ok) {
        setManualSendStatus(buildManualSendStatus(payload));
        toast.error(payload.reason || payload.error?.message || "Не удалось отправить сообщение.");
        return;
      }
      if (payload.workspace) {
        queryClient.setQueryData(["chat-workspace", variables.chatKey], payload.workspace);
      }
      markReplySent(variables.chatKey, {
        sourceMessageId: variables.sourceMessageId,
        sourceMessageKey: variables.sourceMessageKey,
      });
      clearReplyDraft(variables.chatKey);
      setOlderMessages([]);
      setManualSendStatus(buildManualSendStatus(payload));
      toast.success(payload.fallback.used ? "Сообщение отправлено через fallback." : "Сообщение отправлено через Desktop.");
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["chats"], type: "active" }),
        queryClient.refetchQueries({ queryKey: ["chat-workspace", variables.chatKey], exact: true }),
        queryClient.refetchQueries({ queryKey: ["fullaccess"], type: "active" }),
      ]);
    },
    onError: (error) => {
      setManualSendStatus({
        status: "failed",
        message: error instanceof Error ? error.message : "Не удалось отправить сообщение.",
        backend: null,
        sentMessageKey: null,
        timestamp: new Date().toISOString(),
        tone: "error",
      });
      toast.error(error instanceof Error ? error.message : "Не удалось отправить сообщение.");
    },
    onSettled: () => {
      sendInFlightRef.current = false;
    },
  });
  const autopilotGlobalMutation = useMutation({
    mutationFn: (enabled: boolean) => api.updateAutopilotGlobal({ master_enabled: enabled }),
    onSuccess: async () => {
      toast.success("Глобальный режим автопилота обновлён.");
      if (selectedChat?.chatKey) {
        await queryClient.refetchQueries({ queryKey: ["chat-workspace", selectedChat.chatKey], exact: true });
      }
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить master switch.");
    },
  });
  const autopilotChatMutation = useMutation({
    mutationFn: ({
      localChatId,
      chatKey: _chatKey,
      payload,
    }: {
      localChatId: number;
      chatKey: string;
      payload: { trusted?: boolean; mode?: string };
    }) => api.updateChatAutopilot(localChatId, payload),
    onSuccess: async (_payload, variables) => {
      toast.success("Настройки автопилота для чата обновлены.");
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["chat-workspace", variables.chatKey], exact: true }),
        queryClient.refetchQueries({ queryKey: ["chats"], type: "active" }),
      ]);
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить автопилот чата.");
    },
  });
  const tailMessageItems = safeArray(workspaceQuery.data?.messages);
  const messageItems = mergeMessageLists(olderMessages, tailMessageItems);
  const replyPayload = workspaceQuery.data?.reply ?? null;
  const replyContext = normalizeReplyContextPayload(workspaceQuery.data?.replyContext);
  const autopilotPayload = workspaceQuery.data?.autopilot ?? null;
  const freshness = workspaceQuery.data?.freshness ?? null;
  const workspaceStatus = normalizeWorkspaceStatusPayload(workspaceQuery.data?.status);
  const activeChat =
    selectedChat && workspaceQuery.data?.chat
      ? {
          ...selectedChat,
          ...workspaceQuery.data.chat,
          unreadCount: selectedChat.unreadCount,
          unreadMentionCount: selectedChat.unreadMentionCount,
          pinned: selectedChat.pinned,
          muted: selectedChat.muted,
          archived: selectedChat.archived,
        }
      : selectedChat;

  useEffect(() => {
    const lastMessage = messageItems.length > 0 ? messageItems[messageItems.length - 1] : null;
    if (!selectedChat?.chatKey || !lastMessage) {
      return;
    }
    if (
      selectedChatWorkspace?.seenMessageKey === lastMessage.messageKey
      && selectedChatWorkspace?.seenMessageId === (lastMessage.localMessageId ?? null)
    ) {
      return;
    }
    markChatSeen(selectedChat.chatKey, {
      messageId: lastMessage.localMessageId,
      messageKey: lastMessage.messageKey,
    });
  }, [
    messageItems,
    markChatSeen,
    selectedChat?.chatKey,
    selectedChatWorkspace?.seenMessageId,
    selectedChatWorkspace?.seenMessageKey,
  ]);

  useEffect(() => {
    if (!selectedChat || selectedChat.syncStatus !== "fullaccess") {
      return;
    }
    const nextSyncAt = freshness?.lastSyncAt || null;
    if (!nextSyncAt || nextSyncAt === lastWorkspaceSyncAtRef.current) {
      return;
    }
    lastWorkspaceSyncAtRef.current = nextSyncAt;
    void queryClient.refetchQueries({ queryKey: ["chats"], type: "active" });
  }, [freshness?.lastSyncAt, queryClient, selectedChat]);

  const loadOlderMessages = async () => {
    if (!selectedChat || loadingOlder) {
      return;
    }
    const beforeRuntimeMessageId =
      olderMessages[0]?.runtimeMessageId
      || tailMessageItems[0]?.runtimeMessageId
      || workspaceQuery.data?.history?.beforeRuntimeMessageId
      || null;
    if (beforeRuntimeMessageId === null) {
      return;
    }

    setLoadingOlder(true);
    try {
      const payload = await api.chatMessages(selectedChat.id, 50, beforeRuntimeMessageId);
      setOlderMessages((current) => mergeMessageLists(safeArray(payload.messages), current));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось догрузить историю.");
    } finally {
      setLoadingOlder(false);
    }
  };

  const refreshWorkspace = async () => {
    if (selectedChat) {
      if (selectedChat.syncStatus === "fullaccess" && fullaccessReady) {
        if (selectedLocalChatId === null) {
          toast.error("Этот чат пока не связан с legacy source, поэтому manual sync недоступен.");
          return;
        }
        try {
          await syncChatMutation.mutateAsync({
            chatId: selectedLocalChatId,
            chatKey: selectedChat.chatKey,
            chatTitle: selectedChat.title,
            trigger: "manual",
          });
        } catch {
          return;
        }
        return;
      }
    }

    await Promise.all([
      queryClient.refetchQueries({ queryKey: ["chats"], type: "active" }),
      queryClient.refetchQueries({ queryKey: ["chat-workspace", selectedChat?.chatKey], exact: true }),
    ]);
    toast.success("Контекст обновлён.");
  };

  const syncIndicator =
    selectedChat?.syncStatus === "fullaccess"
      ? syncChatMutation.isPending || (workspaceQuery.isFetching && fullaccessReady)
        ? "Активный чат сейчас синхронизируется"
        : freshness?.syncError
          ? `Активный чат: авто-sync с ошибкой`
          : freshness?.updatedNow
            ? "Активный чат только что обновлён"
            : freshness?.label || null
      : workspaceStatus?.source === "new"
        ? "Workspace читается через new runtime"
        : workspaceStatus?.source === "fallback_to_legacy"
          ? "Workspace временно откатился на legacy"
          : rosterState?.source === "new"
        ? "Roster идёт из new runtime"
        : rosterState?.source === "fallback_to_legacy"
          ? "New runtime roster деградировал, поэтому сейчас используется legacy"
          : null;

  const handleCopy = async (value: string) => {
    if (!value) {
      return;
    }

    try {
      await navigator.clipboard.writeText(value);
      toast.success("Ответ скопирован.");
    } catch {
      toast.error("Не удалось скопировать текст в буфер обмена.");
    }
  };

  if (chatsQuery.isError) {
    return (
      <WarningState
        title="Чаты не загрузились"
        description={extractErrorMessage(chatsQuery.error, "Не удалось получить список чатов.")}
      />
    );
  }

  return (
    <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[320px_minmax(0,1fr)_400px]">
      <ChatList
        chats={chatItems}
        selectedChatKey={selectedChatKey}
        search={search}
        filter={filter}
        sort={sort}
        favorites={favoriteChatIds}
        workspaceStateByChat={chatWorkspace}
        loading={chatsQuery.isLoading}
        refreshing={chatsQuery.isFetching || syncChatMutation.isPending}
        refreshedAt={chatsQuery.data?.refreshedAt || null}
        syncIndicator={syncIndicator}
        roster={rosterState}
        onSearchChange={setSearch}
        onFilterChange={setFilter}
        onSortChange={setSort}
        onSelectChat={setSelectedChatKey}
        onToggleFavorite={toggleFavoriteChat}
        onRefresh={() => {
          void refreshWorkspace();
        }}
      />

      <MessageList
        chat={activeChat}
        messages={messageItems}
        loading={workspaceQuery.isLoading}
        refreshing={workspaceQuery.isFetching || syncChatMutation.isPending}
        fullaccessReady={fullaccessReady}
        workspaceStatus={workspaceStatus}
        canLoadOlder={Boolean(workspaceStatus?.availability.canLoadOlder)}
        loadingOlder={loadingOlder}
        lastUpdatedAt={workspaceQuery.data?.refreshedAt || chatsQuery.data?.refreshedAt || null}
        freshness={freshness}
        errorMessage={
          workspaceQuery.isError
            ? extractErrorMessage(workspaceQuery.error, "Не удалось загрузить рабочий контекст чата.")
            : null
        }
        onLoadOlder={() => {
          void loadOlderMessages();
        }}
        onRefresh={() => {
          void refreshWorkspace();
        }}
        onSyncChat={() => {
          if (!selectedChat) {
            return;
          }
          if (selectedLocalChatId === null) {
            toast.error("Для runtime-only чата manual sync пока недоступен.");
            return;
          }
          syncChatMutation.mutate({
            chatId: selectedLocalChatId,
            chatKey: selectedChat.chatKey,
            chatTitle: selectedChat.title,
            trigger: "manual",
          });
        }}
      />

      <ReplyPanel
        reply={replyPayload}
        replyContext={replyContext}
        autopilot={autopilotPayload}
        freshness={freshness}
        workspaceStatus={workspaceStatus}
        workflowState={selectedChatWorkspace}
        loading={workspaceQuery.isLoading}
        refreshing={workspaceQuery.isFetching || syncChatMutation.isPending}
        sending={sendMessageMutation.isPending}
        sendStatus={manualSendStatus}
        autopilotUpdating={autopilotGlobalMutation.isPending || autopilotChatMutation.isPending}
        errorMessage={
          workspaceQuery.isError
            ? extractErrorMessage(workspaceQuery.error, "Не удалось собрать reply preview.")
            : null
        }
        onRefresh={() => {
          void refreshWorkspace();
        }}
        onCopy={handleCopy}
        onUseDraft={(text, sourceMessageId, sourceMessageKey) => {
          if (!selectedChat?.chatKey) {
            return;
          }
          saveReplyDraft(selectedChat.chatKey, {
            text,
            sourceMessageId,
            sourceMessageKey,
            focusLabel: replyContext?.focusLabel ?? replyPayload?.suggestion?.focusLabel ?? null,
            sourceMessagePreview:
              replyContext?.sourceMessagePreview
              || replyPayload?.sourceMessagePreview
              || replyPayload?.suggestion?.sourceMessagePreview
              || null,
            replyOpportunityMode:
              replyContext?.replyOpportunityMode
              || replyPayload?.suggestion?.replyOpportunityMode
              || null,
          });
          toast.success("Черновик сохранён локально.");
        }}
        onSend={(text, sourceMessageId, sourceMessageKey, draftScopeKey) => {
          if (!selectedChat?.chatKey) {
            return;
          }
          const cleanedText = text.trim();
          if (!cleanedText) {
            setManualSendStatus({
              status: "failed",
              message: "Нельзя отправить пустое сообщение.",
              backend: null,
              sentMessageKey: null,
              timestamp: new Date().toISOString(),
              tone: "error",
            });
            toast.error("Нельзя отправить пустое сообщение.");
            return;
          }
          if (sendInFlightRef.current || sendMessageMutation.isPending) {
            setManualSendStatus({
              status: "failed",
              message: "Отправка уже выполняется. Повторный клик заблокирован.",
              backend: null,
              sentMessageKey: null,
              timestamp: new Date().toISOString(),
              tone: "warning",
            });
            return;
          }
          sendInFlightRef.current = true;
          setManualSendStatus({
            status: "pending",
            message: "Отправка черновика...",
            backend: workspaceStatus?.sendPath && "effective" in workspaceStatus.sendPath
              ? String(workspaceStatus.sendPath.effective)
              : workspaceStatus?.effectiveBackend ?? null,
            sentMessageKey: null,
            timestamp: new Date().toISOString(),
            tone: "pending",
          });
          sendMessageMutation.mutate({
            chatId: selectedChat.id,
            chatKey: selectedChat.chatKey,
            text: cleanedText,
            sourceMessageId,
            sourceMessageKey,
            draftScopeKey,
            clientSendId: buildClientSendId(selectedChat.chatKey),
          });
        }}
        onMarkSent={(sourceMessageId, sourceMessageKey) => {
          if (!selectedChat?.chatKey) {
            return;
          }
          markReplySent(selectedChat.chatKey, {
            sourceMessageId,
            sourceMessageKey,
          });
          clearReplyDraft(selectedChat.chatKey);
          toast.success("Локальная отметка «отправлено» сохранена.");
        }}
        onClearDraft={() => {
          if (!selectedChat?.chatKey) {
            return;
          }
          clearReplyDraft(selectedChat.chatKey);
          toast.success("Черновик очищен.");
        }}
        onUpdateAutopilotGlobal={(enabled) => {
          autopilotGlobalMutation.mutate(enabled);
        }}
        onUpdateChatAutopilot={(payload) => {
          if (selectedLocalChatId === null) {
            return;
          }
          if (!selectedChat?.chatKey) {
            return;
          }
          autopilotChatMutation.mutate({
            localChatId: selectedLocalChatId,
            chatKey: selectedChat.chatKey,
            payload,
          });
        }}
      />
    </div>
  );
}

function mergeMessageLists(...pages: Array<MessageItem[] | undefined>): MessageItem[] {
  const byKey = new Map<string, MessageItem>();
  for (const page of pages) {
    for (const message of safeArray(page)) {
      byKey.set(message.messageKey, message);
    }
  }
  return Array.from(byKey.values()).sort((left, right) => left.runtimeMessageId - right.runtimeMessageId);
}

function buildManualSendStatus(payload: ChatSendPayload) {
  const sentMessageKey =
    typeof payload.sentMessageIdentity?.messageKey === "string"
      ? payload.sentMessageIdentity.messageKey
      : payload.sentMessage?.messageKey ?? null;
  return {
    status: payload.status,
    message: payload.ok
      ? payload.fallback.used
        ? payload.reason || "Сообщение отправлено через fallback."
        : "Сообщение отправлено."
      : payload.reason || payload.error?.message || "Не удалось отправить сообщение.",
    backend: payload.effectiveBackend,
    sentMessageKey,
    timestamp: new Date().toISOString(),
    tone: payload.ok
      ? payload.status === "degraded" || payload.fallback.used
        ? "warning"
        : "success"
      : "error",
  } satisfies {
    status: string;
    message: string;
    backend: string | null;
    sentMessageKey: string | null;
    timestamp: string;
    tone: "success" | "error" | "pending" | "warning";
  };
}

function buildClientSendId(chatKey: string): string {
  return `${chatKey}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}
