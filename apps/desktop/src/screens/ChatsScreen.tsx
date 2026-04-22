import { startTransition, useDeferredValue, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";

import { ChatList } from "@/components/system/ChatList";
import { MessageList } from "@/components/system/MessageList";
import { ReplyPanel } from "@/components/system/ReplyPanel";
import { WarningState } from "@/components/system/WarningState";

export function ChatsScreen() {
  const queryClient = useQueryClient();
  const selectedChatId = useAppStore((state) => state.selectedChatId);
  const setSelectedChatId = useAppStore((state) => state.setSelectedChatId);
  const favoriteChatIds = useAppStore((state) => state.favoriteChatIds);
  const toggleFavoriteChat = useAppStore((state) => state.toggleFavoriteChat);

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
    refetchInterval: 10_000,
  });

  useEffect(() => {
    const items = chatsQuery.data?.items || [];
    if (items.length === 0) {
      if (selectedChatId !== null) {
        startTransition(() => setSelectedChatId(null));
      }
      return;
    }

    const stillExists = items.some((item) => item.id === selectedChatId);
    if (!stillExists) {
      startTransition(() => setSelectedChatId(items[0]?.id ?? null));
    }
  }, [chatsQuery.data?.items, selectedChatId, setSelectedChatId]);

  const selectedChat = chatsQuery.data?.items.find((item) => item.id === selectedChatId) || null;

  const messagesQuery = useQuery({
    queryKey: ["chat-messages", selectedChatId],
    queryFn: () => api.chatMessages(selectedChatId as number),
    enabled: selectedChatId !== null,
    refetchInterval: 10_000,
  });

  const replyQuery = useQuery({
    queryKey: ["reply-preview", selectedChatId],
    queryFn: () => api.replyPreview(selectedChatId as number),
    enabled: selectedChatId !== null,
    refetchInterval: 15_000,
  });

  const replyRefreshMutation = useMutation({
    mutationFn: () => api.replyPreview(selectedChatId as number),
    onSuccess: async (payload) => {
      queryClient.setQueryData(["reply-preview", selectedChatId], payload);
      await queryClient.invalidateQueries({ queryKey: ["chat-messages", selectedChatId] });
      toast.success("Контекст и reply preview обновлены.");
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить reply preview.");
    },
  });

  const refreshContext = async () => {
    if (selectedChatId === null) {
      return;
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat-messages", selectedChatId] }),
      queryClient.invalidateQueries({ queryKey: ["reply-preview", selectedChatId] }),
      queryClient.invalidateQueries({ queryKey: ["chats"] }),
    ]);
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
        description={
          chatsQuery.error instanceof Error
            ? chatsQuery.error.message
            : "Не удалось получить список чатов."
        }
      />
    );
  }

  return (
    <div className="grid min-h-[calc(100vh-13rem)] gap-4 xl:grid-cols-[320px_minmax(0,1fr)_380px]">
      <ChatList
        chats={chatsQuery.data?.items || []}
        selectedChatId={selectedChatId}
        search={search}
        filter={filter}
        sort={sort}
        favorites={favoriteChatIds}
        loading={chatsQuery.isLoading}
        onSearchChange={setSearch}
        onFilterChange={setFilter}
        onSortChange={setSort}
        onSelectChat={setSelectedChatId}
        onToggleFavorite={toggleFavoriteChat}
        onRefresh={() => queryClient.invalidateQueries({ queryKey: ["chats"] })}
      />

      <MessageList
        chat={selectedChat}
        messages={messagesQuery.data?.messages || []}
        loading={messagesQuery.isLoading}
        onRefresh={refreshContext}
      />

      <ReplyPanel
        reply={replyQuery.data || null}
        loading={replyQuery.isLoading || replyRefreshMutation.isPending}
        onRefresh={() => {
          if (selectedChatId !== null) {
            replyRefreshMutation.mutate();
          }
        }}
        onCopy={handleCopy}
      />
    </div>
  );
}
