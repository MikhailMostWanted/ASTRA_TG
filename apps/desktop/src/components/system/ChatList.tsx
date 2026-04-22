import {
  BellDot,
  Clock3,
  LoaderCircle,
  Pin,
  RefreshCcw,
  Search,
  Star,
} from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCompactNumber, formatDateTime, formatRelativeTime, initials } from "@/lib/format";
import { safeArray, safeRecord } from "@/lib/runtime-guards";
import type { ChatItem } from "@/lib/types";
import type { ChatWorkspaceState } from "@/stores/app-store";
import { cn } from "@/lib/utils";

import { EmptyState } from "./EmptyState";

interface ChatListProps {
  chats: ChatItem[];
  selectedChatId: number | null;
  search: string;
  filter: string;
  sort: string;
  favorites: number[];
  workspaceStateByChat: Record<number, ChatWorkspaceState>;
  loading?: boolean;
  refreshing?: boolean;
  refreshedAt?: string | null;
  syncIndicator?: string | null;
  onSearchChange: (value: string) => void;
  onFilterChange: (value: string) => void;
  onSortChange: (value: string) => void;
  onSelectChat: (chatId: number) => void;
  onToggleFavorite: (chatId: number) => void;
  onRefresh: () => void;
}

const syncLabelMap: Record<string, string> = {
  fullaccess: "full-access",
  local: "локально",
  empty: "без sync",
};

export function ChatList({
  chats,
  selectedChatId,
  search,
  filter,
  sort,
  favorites,
  workspaceStateByChat,
  loading = false,
  refreshing = false,
  refreshedAt = null,
  syncIndicator = null,
  onSearchChange,
  onFilterChange,
  onSortChange,
  onSelectChat,
  onToggleFavorite,
  onRefresh,
}: ChatListProps) {
  const safeChats = safeArray(chats);
  const safeFavorites = safeArray(favorites).filter(
    (item): item is number => typeof item === "number" && Number.isFinite(item),
  );
  const safeWorkspaceState = safeRecord<ChatWorkspaceState>(workspaceStateByChat);

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
      <div className="border-b border-white/7 px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Workspace</div>
            <div className="text-base font-semibold text-white">Живые чаты</div>
            <div className="text-sm leading-6 text-slate-400">
              Компактный список для быстрого выбора, sync и контроля хвостов.
            </div>
          </div>
          <Button
            variant="outline"
            size="icon-sm"
            className="border-white/8 bg-black/18 text-slate-100"
            onClick={onRefresh}
            disabled={refreshing}
          >
            {refreshing ? <LoaderCircle className="animate-spin" /> : <RefreshCcw />}
          </Button>
        </div>

        <div className="mt-4 relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <Input
            className="w-full border-white/8 bg-black/16 pl-10 text-slate-100 placeholder:text-slate-500"
            placeholder="Поиск по имени, @username или chat_id"
            value={search}
            onChange={(event) => onSearchChange(event.currentTarget.value)}
          />
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          <Select value={filter} onValueChange={onFilterChange}>
            <SelectTrigger className="w-full border-white/8 bg-black/16 text-slate-100">
              <SelectValue placeholder="Фильтр" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">Все</SelectItem>
                <SelectItem value="enabled">Активные</SelectItem>
                <SelectItem value="reply">Где нужен reply</SelectItem>
                <SelectItem value="fullaccess">Через full-access</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>

          <Select value={sort} onValueChange={onSortChange}>
            <SelectTrigger className="w-full border-white/8 bg-black/16 text-slate-100">
              <SelectValue placeholder="Сортировка" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="activity">По свежести</SelectItem>
                <SelectItem value="messages">По объёму</SelectItem>
                <SelectItem value="title">По имени</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3 text-xs text-slate-500">
          <div>{formatCompactNumber(safeChats.length)} в выборке</div>
          <div className="truncate">
            {syncIndicator || (refreshedAt ? `Обновлено ${formatDateTime(refreshedAt)}` : "Ещё не обновлялось")}
          </div>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2 p-3">
          {loading && safeChats.length === 0 ? <ChatListSkeleton /> : null}

          {!loading && safeChats.length === 0 ? (
            <EmptyState
              title="Чаты не найдены"
              description="Проверь фильтры или подтяни источники и full-access синхронизацию."
            />
          ) : null}

          {safeChats.map((chat) => {
            const isSelected = chat.id === selectedChatId;
            const isFavorite = safeFavorites.includes(chat.id);
            const workspaceState = safeWorkspaceState[chat.id];
            const seenMessageId = workspaceState?.seenMessageId ?? null;
            const draftSourceMessageId = workspaceState?.draftSourceMessageId ?? null;
            const sentSourceMessageId = workspaceState?.sentSourceMessageId ?? null;
            const hasNewMessages = Boolean(
              seenMessageId !== null
              && chat.lastMessageId !== null
              && Number(chat.lastMessageId) > Number(seenMessageId),
            );
            const hasDraft = Boolean(
              workspaceState?.draftText
              && draftSourceMessageId !== null
              && draftSourceMessageId === chat.lastMessageId,
            );
            const needsReply = Boolean(
              chat.type !== "channel"
              && chat.lastDirection === "inbound"
              && sentSourceMessageId !== chat.lastMessageId,
            );

            return (
              <div
                key={chat.id}
                role="button"
                tabIndex={0}
                className={cn(
                  "cursor-pointer rounded-[24px] border border-transparent bg-transparent px-3 py-3 text-left transition-all active:translate-y-px hover:border-white/10 hover:bg-white/[0.045]",
                  isSelected && "border-cyan-300/18 bg-cyan-400/9 shadow-[0_14px_38px_rgba(8,145,178,0.16)]",
                )}
                onClick={() => onSelectChat(chat.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelectChat(chat.id);
                  }
                }}
              >
                <div className="flex items-start gap-3">
                  <Avatar className="size-11 border border-white/8 bg-white/[0.04]">
                    <AvatarImage src={chat.avatarUrl || undefined} alt={chat.title} />
                    <AvatarFallback className="bg-cyan-400/10 text-cyan-100">
                      {initials(chat.title)}
                    </AvatarFallback>
                  </Avatar>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-white">{chat.title}</div>
                        <div className="truncate text-xs text-slate-500">
                          {chat.handle ? `@${chat.handle}` : chat.reference}
                        </div>
                      </div>

                      <button
                        type="button"
                        className={cn(
                          "rounded-full p-1 text-slate-500 transition-all hover:bg-white/8 hover:text-white active:translate-y-px",
                          isFavorite && "text-amber-200",
                        )}
                        onClick={(event) => {
                          event.stopPropagation();
                          onToggleFavorite(chat.id);
                        }}
                      >
                        {isFavorite ? <Star className="fill-current" /> : <Pin />}
                      </button>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                        {syncLabelMap[chat.syncStatus] || chat.syncStatus}
                      </Badge>
                      {needsReply ? (
                        <Badge variant="outline" className="border-0 bg-rose-400/12 text-rose-100 ring-1 ring-rose-300/15">
                          Нужен ответ
                        </Badge>
                      ) : null}
                      {hasDraft ? (
                        <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15">
                          Черновик
                        </Badge>
                      ) : null}
                      {hasNewMessages ? (
                        <Badge variant="outline" className="border-0 bg-cyan-400/12 text-cyan-100 ring-1 ring-cyan-300/15">
                          Новое
                        </Badge>
                      ) : null}
                    </div>

                    <div className="mt-3 line-clamp-2 text-sm leading-6 text-slate-300">
                      {chat.lastMessagePreview}
                    </div>

                    <div className="mt-3 flex items-center justify-between gap-3">
                      <div className="truncate text-xs text-slate-500">
                        {formatCompactNumber(chat.messageCount)} сообщений
                        {chat.lastSenderName ? ` • ${chat.lastSenderName}` : ""}
                      </div>
                      <div className="flex shrink-0 items-center gap-1 text-xs text-slate-500">
                        <Clock3 className="size-3" />
                        {formatRelativeTime(chat.lastMessageAt)}
                      </div>
                    </div>

                    {workspaceState?.draftUpdatedAt || workspaceState?.sentAt ? (
                      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                        {workspaceState.draftUpdatedAt ? (
                          <span>Черновик {formatDateTime(workspaceState.draftUpdatedAt)}</span>
                        ) : null}
                        {workspaceState.sentAt ? (
                          <span className="inline-flex items-center gap-1">
                            <BellDot className="size-3" />
                            Отмечено отправленным {formatDateTime(workspaceState.sentAt)}
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </ScrollArea>
    </section>
  );
}

function ChatListSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="rounded-[24px] border border-white/6 bg-white/[0.03] px-3 py-3">
          <div className="flex items-start gap-3">
            <Skeleton className="size-11 rounded-full bg-white/10" />
            <div className="min-w-0 flex-1 space-y-3">
              <Skeleton className="h-4 w-2/5 bg-white/10" />
              <Skeleton className="h-3 w-1/3 bg-white/10" />
              <Skeleton className="h-3 w-full bg-white/10" />
              <Skeleton className="h-3 w-4/5 bg-white/10" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
