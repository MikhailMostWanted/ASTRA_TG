import { startTransition, useDeferredValue, useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ChatList } from "@/components/system/ChatList";
import { MessageList } from "@/components/system/MessageList";
import { ReplyPanel } from "@/components/system/ReplyPanel";
import { WarningState } from "@/components/system/WarningState";
import { api } from "@/lib/api";
import { extractErrorMessage, safeArray } from "@/lib/runtime-guards";
import { useAppStore } from "@/stores/app-store";

const CHAT_POLL_MS = 7_000;
const MESSAGE_POLL_MS = 6_000;
const REPLY_POLL_MS = 8_000;
const AUTO_SYNC_MS = 30_000;

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

  const selectedChat = chatItems.find((item) => item.id === selectedChatId) || null;
  const selectedChatWorkspace = selectedChatId !== null ? chatWorkspace[selectedChatId] || null : null;
  const fullaccessReady = Boolean(fullaccessQuery.data?.status.readyForManualSync);

  const messagesQuery = useQuery({
    queryKey: ["chat-messages", selectedChatId],
    queryFn: () => api.chatMessages(selectedChatId as number, 60),
    enabled: selectedChatId !== null,
    refetchInterval: MESSAGE_POLL_MS,
  });

  const replyQuery = useQuery({
    queryKey: ["reply-preview", selectedChatId],
    queryFn: () => api.replyPreview(selectedChatId as number),
    enabled: selectedChatId !== null,
    refetchInterval: REPLY_POLL_MS,
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
    }) => api.syncSource(chatId).then((payload) => ({ payload, chatTitle, silent })),
    onSuccess: async ({ payload, chatTitle, silent }) => {
      if (!silent) {
        toast.success(
          `Чат «${chatTitle}» синхронизирован: +${payload.createdCount}, обновлено ${payload.updatedCount}.`,
        );
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["chats"] }),
        queryClient.invalidateQueries({ queryKey: ["chat-messages", payload.localChatId] }),
        queryClient.invalidateQueries({ queryKey: ["reply-preview", payload.localChatId] }),
      ]);
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось синхронизировать выбранный чат.");
    },
  });
  const messageItems = safeArray(messagesQuery.data?.messages);
  const replyPayload = replyQuery.data ?? null;

  useEffect(() => {
    const lastMessage = messageItems.length > 0 ? messageItems[messageItems.length - 1] : null;
    if (selectedChatId === null || !lastMessage) {
      return;
    }
    markChatSeen(selectedChatId, lastMessage.id);
  }, [messageItems, markChatSeen, selectedChatId]);

  useEffect(() => {
    if (!selectedChat || selectedChat.syncStatus !== "fullaccess" || !fullaccessReady) {
      return;
    }

    const timer = window.setInterval(() => {
      if (syncChatMutation.isPending) {
        return;
      }
      syncChatMutation.mutate({
        chatId: selectedChat.id,
        chatTitle: selectedChat.title,
        silent: true,
      });
    }, AUTO_SYNC_MS);

    return () => window.clearInterval(timer);
  }, [fullaccessReady, selectedChat, syncChatMutation]);

  const refreshWorkspace = async () => {
    if (selectedChat) {
      if (selectedChat.syncStatus === "fullaccess" && fullaccessReady) {
        syncChatMutation.mutate({
          chatId: selectedChat.id,
          chatTitle: selectedChat.title,
        });
        return;
      }
    }

    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chats"] }),
      queryClient.invalidateQueries({ queryKey: ["chat-messages", selectedChatId] }),
      queryClient.invalidateQueries({ queryKey: ["reply-preview", selectedChatId] }),
    ]);
    toast.success("Контекст обновлён.");
  };

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
        loading={messagesQuery.isLoading}
        refreshing={messagesQuery.isFetching || syncChatMutation.isPending}
        fullaccessReady={fullaccessReady}
        lastUpdatedAt={messagesQuery.data?.refreshedAt || chatsQuery.data?.refreshedAt || null}
        errorMessage={
          messagesQuery.isError
            ? extractErrorMessage(messagesQuery.error, "Не удалось загрузить ленту сообщений.")
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
          });
        }}
      />

      <ReplyPanel
        reply={replyPayload}
        workflowState={selectedChatWorkspace}
        loading={replyQuery.isLoading}
        refreshing={replyQuery.isFetching || syncChatMutation.isPending}
        errorMessage={
          replyQuery.isError
            ? extractErrorMessage(replyQuery.error, "Не удалось собрать reply preview.")
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
