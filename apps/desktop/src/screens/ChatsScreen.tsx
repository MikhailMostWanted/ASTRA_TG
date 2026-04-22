import { startTransition, useDeferredValue, useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ChatList } from "@/components/system/ChatList";
import { MessageList } from "@/components/system/MessageList";
import { ReplyPanel } from "@/components/system/ReplyPanel";
import { WarningState } from "@/components/system/WarningState";
import { api } from "@/lib/api";
import { extractErrorMessage, safeArray } from "@/lib/runtime-guards";
import { useAppStore } from "@/stores/app-store";

const CHAT_POLL_MS = 6_000;
const FULLACCESS_WORKSPACE_POLL_MS = 5_000;
const LOCAL_WORKSPACE_POLL_MS = 7_000;

export function ChatsScreen() {
  const queryClient = useQueryClient();
  const rawSelectedChatId = useAppStore((state) => state.selectedChatId);
  const setSelectedChatId = useAppStore((state) => state.setSelectedChatId);
  const rawFavoriteChatIds = useAppStore((state) => state.favoriteChatIds);
  const toggleFavoriteChat = useAppStore((state) => state.toggleFavoriteChat);
  const rawChatWorkspace = useAppStore((state) => state.chatWorkspace);
  const markChatSeen = useAppStore((state) => state.markChatSeen);
  const saveReplyDraft = useAppStore((state) => state.saveReplyDraft);
  const markReplySent = useAppStore((state) => state.markReplySent);
  const clearReplyDraft = useAppStore((state) => state.clearReplyDraft);
  const selectedChatId =
    typeof rawSelectedChatId === "number" && Number.isFinite(rawSelectedChatId)
      ? rawSelectedChatId
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

  useEffect(() => {
    if (chatItems.length === 0) {
      if (selectedChatId !== null) {
        startTransition(() => setSelectedChatId(null));
      }
      return;
    }

    const stillExists = chatItems.some((item) => item.id === selectedChatId);
    if (!stillExists) {
      startTransition(() => setSelectedChatId(chatItems[0]?.id ?? null));
    }
  }, [chatItems, selectedChatId, setSelectedChatId]);

  useEffect(() => {
    lastWorkspaceSyncAtRef.current = null;
  }, [selectedChatId]);

  const selectedChat = chatItems.find((item) => item.id === selectedChatId) || null;
  const selectedChatWorkspace = selectedChatId !== null ? chatWorkspace[selectedChatId] || null : null;
  const fullaccessReady = Boolean(fullaccessQuery.data?.status.readyForManualSync);

  const workspaceQuery = useQuery({
    queryKey: ["chat-workspace", selectedChatId],
    queryFn: () => api.chatWorkspace(selectedChatId as number, 60),
    enabled: selectedChatId !== null,
    refetchInterval:
      selectedChat?.syncStatus === "fullaccess"
        ? FULLACCESS_WORKSPACE_POLL_MS
        : LOCAL_WORKSPACE_POLL_MS,
  });

  const syncChatMutation = useMutation({
    mutationFn: ({
      chatId,
      chatTitle,
      silent = false,
    }: {
      chatId: number;
      chatTitle: string;
      silent?: boolean;
      trigger?: "manual" | "auto";
    }) => api.syncSource(chatId).then((payload) => ({ payload, chatTitle, silent })),
    onSuccess: async ({ payload, chatTitle, silent }) => {
      if (!silent) {
        toast.success(
          `Чат «${chatTitle}» синхронизирован: +${payload.createdCount}, обновлено ${payload.updatedCount}.`,
        );
      }
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["chats"], type: "active" }),
        queryClient.refetchQueries({ queryKey: ["chat-workspace", payload.localChatId], exact: true }),
        queryClient.refetchQueries({ queryKey: ["fullaccess"], type: "active" }),
      ]);
    },
    onError: (error, variables) => {
      if (variables.trigger !== "auto") {
        toast.error(error instanceof Error ? error.message : "Не удалось синхронизировать выбранный чат.");
      }
    },
  });
  const messageItems = safeArray(workspaceQuery.data?.messages);
  const replyPayload = workspaceQuery.data?.reply ?? null;
  const freshness = workspaceQuery.data?.freshness ?? null;

  useEffect(() => {
    const lastMessage = messageItems.length > 0 ? messageItems[messageItems.length - 1] : null;
    if (selectedChatId === null || !lastMessage) {
      return;
    }
    markChatSeen(selectedChatId, lastMessage.id);
  }, [messageItems, markChatSeen, selectedChatId]);

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

  const refreshWorkspace = async () => {
    if (selectedChat) {
      if (selectedChat.syncStatus === "fullaccess" && fullaccessReady) {
        try {
          await syncChatMutation.mutateAsync({
            chatId: selectedChat.id,
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
      queryClient.refetchQueries({ queryKey: ["chat-workspace", selectedChatId], exact: true }),
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
        selectedChatId={selectedChatId}
        search={search}
        filter={filter}
        sort={sort}
        favorites={favoriteChatIds}
        workspaceStateByChat={chatWorkspace}
        loading={chatsQuery.isLoading}
        refreshing={chatsQuery.isFetching || syncChatMutation.isPending}
        refreshedAt={chatsQuery.data?.refreshedAt || null}
        syncIndicator={syncIndicator}
        onSearchChange={setSearch}
        onFilterChange={setFilter}
        onSortChange={setSort}
        onSelectChat={setSelectedChatId}
        onToggleFavorite={toggleFavoriteChat}
        onRefresh={() => {
          void refreshWorkspace();
        }}
      />

      <MessageList
        chat={selectedChat}
        messages={messageItems}
        loading={workspaceQuery.isLoading}
        refreshing={workspaceQuery.isFetching || syncChatMutation.isPending}
        fullaccessReady={fullaccessReady}
        lastUpdatedAt={workspaceQuery.data?.refreshedAt || chatsQuery.data?.refreshedAt || null}
        freshness={freshness}
        errorMessage={
          workspaceQuery.isError
            ? extractErrorMessage(workspaceQuery.error, "Не удалось загрузить рабочий контекст чата.")
            : null
        }
        onRefresh={() => {
          void refreshWorkspace();
        }}
        onSyncChat={() => {
          if (!selectedChat) {
            return;
          }
          syncChatMutation.mutate({
            chatId: selectedChat.id,
            chatTitle: selectedChat.title,
            trigger: "manual",
          });
        }}
      />

      <ReplyPanel
        reply={replyPayload}
        freshness={freshness}
        workflowState={selectedChatWorkspace}
        loading={workspaceQuery.isLoading}
        refreshing={workspaceQuery.isFetching || syncChatMutation.isPending}
        errorMessage={
          workspaceQuery.isError
            ? extractErrorMessage(workspaceQuery.error, "Не удалось собрать reply preview.")
            : null
        }
        onRefresh={() => {
          void refreshWorkspace();
        }}
        onCopy={handleCopy}
        onUseDraft={(text, sourceMessageId) => {
          if (selectedChatId === null) {
            return;
          }
          saveReplyDraft(selectedChatId, text, sourceMessageId);
          toast.success("Черновик сохранён локально.");
        }}
        onMarkSent={(sourceMessageId) => {
          if (selectedChatId === null) {
            return;
          }
          markReplySent(selectedChatId, sourceMessageId);
          clearReplyDraft(selectedChatId);
          toast.success("Локальная отметка «отправлено» сохранена.");
        }}
        onClearDraft={() => {
          if (selectedChatId === null) {
            return;
          }
          clearReplyDraft(selectedChatId);
          toast.success("Черновик очищен.");
        }}
      />
    </div>
  );
}
