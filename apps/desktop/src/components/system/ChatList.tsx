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
import { buildAutopilotCopy, buildRosterCopy, formatAutopilotMode, toneBadgeClasses } from "@/lib/chat-ux";
import { formatCompactNumber, formatDateTime, formatRelativeTime, initials } from "@/lib/format";
import { safeArray, safeRecord } from "@/lib/runtime-guards";
import type { AutopilotPayload, ChatItem, ChatRosterStatePayload, LiveStatusPayload, WorkspaceStatusPayload } from "@/lib/types";
import type { ChatWorkspaceState } from "@/stores/app-store";
import { cn } from "@/lib/utils";

import { EmptyState } from "./EmptyState";

interface ChatListProps {
  chats: ChatItem[];
  selectedChatKey: string | null;
  search: string;
  filter: string;
  sort: string;
  favorites: number[];
  workspaceStateByChat: Record<string, ChatWorkspaceState>;
  loading?: boolean;
  refreshing?: boolean;
  refreshedAt?: string | null;
  syncIndicator?: string | null;
  roster?: ChatRosterStatePayload | null;
  live?: LiveStatusPayload | null;
  activeWorkspaceStatus?: WorkspaceStatusPayload | null;
  activeAutopilot?: AutopilotPayload | null;
  onSearchChange: (value: string) => void;
  onFilterChange: (value: string) => void;
  onSortChange: (value: string) => void;
  onSelectChat: (chatKey: string) => void;
  onToggleFavorite: (chatId: number) => void;
  onRefresh: () => void;
}

const syncLabelMap: Record<string, string> = {
  fullaccess: "полный доступ",
  local: "локально",
  runtime: "Telegram",
  empty: "нет истории",
};

export function ChatList({
  chats,
  selectedChatKey,
  search,
  filter,
  sort,
  favorites,
  workspaceStateByChat,
  loading = false,
  refreshing = false,
  refreshedAt = null,
  syncIndicator = null,
  roster = null,
  live = null,
  activeWorkspaceStatus = null,
  activeAutopilot = null,
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
  const rosterCopy = buildRosterCopy(roster, live);
  const autopilotCopy = buildAutopilotCopy(activeAutopilot);
  const activePendingConfirmation = Boolean(
    activeAutopilot?.pendingDraft?.status === "awaiting_confirmation"
      || activeAutopilot?.decision.status === "awaiting_confirmation",
  );

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[22px] border border-white/7 bg-white/[0.035]">
      <div className="border-b border-white/7 px-3 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Пульт</div>
            <div className="text-base font-semibold text-white">Чаты</div>
            <div className="text-xs leading-5 text-slate-400">{rosterCopy.label}</div>
          </div>
          <Button
            variant="outline"
            size="icon-sm"
            className="border-white/8 bg-black/18 text-slate-100"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label={refreshing ? "Обновляю список чатов" : "Обновить список чатов"}
            title={refreshing ? "Обновляю список чатов" : "Обновить список чатов"}
          >
            {refreshing ? <LoaderCircle className="animate-spin" /> : <RefreshCcw />}
          </Button>
        </div>

        <div className="mt-3 relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <Input
            className="h-9 w-full border-white/8 bg-black/16 pl-10 text-sm text-slate-100 placeholder:text-slate-500"
            placeholder="Имя, @username или chat_id"
            value={search}
            onChange={(event) => onSearchChange(event.currentTarget.value)}
          />
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          <Select value={filter} onValueChange={onFilterChange}>
            <SelectTrigger className="h-9 w-full border-white/8 bg-black/16 text-sm text-slate-100">
              <SelectValue placeholder="Фильтр" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">Все</SelectItem>
                <SelectItem value="enabled">Активные</SelectItem>
                <SelectItem value="reply">Нужен ответ</SelectItem>
                <SelectItem value="fullaccess">Через full-access</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>

          <Select value={sort} onValueChange={onSortChange}>
            <SelectTrigger className="h-9 w-full border-white/8 bg-black/16 text-sm text-slate-100">
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
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span>{formatCompactNumber(safeChats.length)} в выборке</span>
            <Badge variant="outline" className={cn("border-0 ring-1", toneBadgeClasses(rosterCopy.tone))}>
              {rosterCopy.label}
            </Badge>
            {activeAutopilot ? (
              <Badge variant="outline" className={cn("border-0 ring-1", toneBadgeClasses(autopilotCopy.tone))}>
                {autopilotCopy.label}
              </Badge>
            ) : null}
          </div>
          <div className="truncate text-right">
            {syncIndicator
              || (roster?.lastUpdatedAt
                ? `Обновлено ${formatDateTime(roster.lastUpdatedAt)}`
                : refreshedAt
                  ? `Обновлено ${formatDateTime(refreshedAt)}`
                  : "Ещё не обновлялось")}
          </div>
        </div>

        {roster?.degradedReason ? (
          <div className="mt-3 rounded-2xl border border-amber-300/10 bg-amber-300/6 px-3 py-2 text-xs leading-5 text-amber-100/85">
            <span className="font-medium text-amber-50">Что случилось: </span>
            {rosterCopy.detail}
          </div>
        ) : null}
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2 p-3">
          {loading && safeChats.length === 0 ? <ChatListSkeleton /> : null}

          {!loading && safeChats.length === 0 ? (
            <EmptyState
              title="Чаты не найдены"
              description="Список пустой для текущих фильтров. Сбрось поиск или обнови список чатов."
              action={
                <Button variant="outline" className="border-white/8 bg-black/18 text-slate-100" onClick={onRefresh}>
                  <RefreshCcw data-icon="inline-start" />
                  Обновить список
                </Button>
              }
            />
          ) : null}

          {safeChats.map((chat) => {
            const isSelected = chat.chatKey === selectedChatKey;
            const isFavorite = safeFavorites.includes(chat.id);
            const workspaceState = safeWorkspaceState[chat.chatKey];
            const latestMessageKey = chat.rosterLastMessageKey || chat.lastMessageKey;
            const latestMessageId = chat.lastMessageId;
            const seenMessageId = workspaceState?.seenMessageId ?? null;
            const seenMessageKey = workspaceState?.seenMessageKey ?? null;
            const draftSourceMessageId = workspaceState?.draftSourceMessageId ?? null;
            const draftSourceMessageKey = workspaceState?.draftSourceMessageKey ?? null;
            const sentSourceMessageId = workspaceState?.sentSourceMessageId ?? null;
            const sentSourceMessageKey = workspaceState?.sentSourceMessageKey ?? null;
            const hasNewMessages = Boolean(
              latestMessageKey
                ? seenMessageKey !== latestMessageKey
                : seenMessageId !== null
                  && latestMessageId !== null
                  && Number(latestMessageId) > Number(seenMessageId),
            );
            const hasDraft = Boolean(
              workspaceState?.draftText
              && (
                latestMessageKey
                  ? draftSourceMessageKey !== null && draftSourceMessageKey === latestMessageKey
                  : draftSourceMessageId !== null && draftSourceMessageId === latestMessageId
              ),
            );
            const needsReply = Boolean(
              chat.type !== "channel"
              && (chat.rosterLastDirection || chat.lastDirection) === "inbound"
              && (
                latestMessageKey
                  ? sentSourceMessageKey !== latestMessageKey
                  : sentSourceMessageId !== latestMessageId
              ),
            );
            const displayPreview = chat.rosterLastMessagePreview || chat.lastMessagePreview;
            const displayActivityAt = chat.rosterLastActivityAt || chat.lastMessageAt;
            const displaySender = chat.rosterLastSenderName || chat.lastSenderName;
            const hasUnread = chat.unreadCount > 0;
            const chatMode = chat.autoReplyMode || (chat.replyAssistEnabled ? "draft" : "off");
            const isActiveDegraded = Boolean(isSelected && activeWorkspaceStatus?.degraded);
            const isActiveFallback = Boolean(isSelected && activeWorkspaceStatus?.source === "fallback_to_legacy");

            return (
              <div
                key={chat.id}
                role="button"
                tabIndex={0}
                className={cn(
                  "cursor-pointer rounded-[18px] border border-transparent bg-transparent px-3 py-2.5 text-left transition-all active:translate-y-px hover:border-white/10 hover:bg-white/[0.045]",
                  isSelected && "border-cyan-300/18 bg-cyan-400/9 shadow-[0_14px_38px_rgba(8,145,178,0.16)]",
                )}
                onClick={() => onSelectChat(chat.chatKey)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelectChat(chat.chatKey);
                  }
                }}
              >
                <div className="flex items-start gap-3">
                  <div className="relative shrink-0">
                    <Avatar className="size-10 border border-white/8 bg-white/[0.04]">
                    <AvatarImage src={chat.avatarUrl || undefined} alt={chat.title} />
                    <AvatarFallback className="bg-cyan-400/10 text-cyan-100">
                      {initials(chat.title)}
                    </AvatarFallback>
                  </Avatar>
                    {hasNewMessages || hasUnread ? (
                      <span className="absolute -right-0.5 -top-0.5 size-3 rounded-full border border-[#07111c] bg-cyan-300" />
                    ) : null}
                  </div>

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
                        aria-label={isFavorite ? "Убрать чат из избранного" : "Добавить чат в избранное"}
                        onClick={(event) => {
                          event.stopPropagation();
                          onToggleFavorite(chat.id);
                        }}
                      >
                        {isFavorite ? <Star className="fill-current" /> : <Pin />}
                      </button>
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                        {syncLabelMap[chat.syncStatus] || chat.syncStatus}
                      </Badge>
                      {chatMode !== "off" ? (
                        <Badge
                          variant="outline"
                          className={cn("border-0 ring-1", toneBadgeClasses(chatMode === "autopilot" ? "danger" : chatMode === "semi_auto" ? "warning" : "info"))}
                        >
                          {formatAutopilotMode(chatMode)}
                        </Badge>
                      ) : null}
                      {chat.pinned ? (
                        <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/12">
                          Закреплён
                        </Badge>
                      ) : null}
                      {chat.muted ? (
                        <Badge variant="outline" className="border-0 bg-slate-400/10 text-slate-200 ring-1 ring-slate-300/10">
                          Без звука
                        </Badge>
                      ) : null}
                      {hasUnread ? (
                        <Badge variant="outline" className="border-0 bg-cyan-400/12 text-cyan-100 ring-1 ring-cyan-300/15">
                          {chat.unreadCount} непрочит.
                        </Badge>
                      ) : null}
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
                      {isSelected && activePendingConfirmation ? (
                        <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15">
                          Ждёт подтверждение
                        </Badge>
                      ) : null}
                      {isActiveFallback ? (
                        <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15">
                          Резервный слой
                        </Badge>
                      ) : null}
                      {isActiveDegraded ? (
                        <Badge variant="outline" className="border-0 bg-rose-400/12 text-rose-100 ring-1 ring-rose-300/15">
                          Нестабильно
                        </Badge>
                      ) : null}
                      {hasNewMessages ? (
                        <Badge variant="outline" className="border-0 bg-cyan-400/12 text-cyan-100 ring-1 ring-cyan-300/15">
                          Новое
                        </Badge>
                      ) : null}
                    </div>

                    <div className="mt-2 line-clamp-2 text-sm leading-5 text-slate-300">
                      {displayPreview}
                    </div>

                    <div className="mt-2 flex items-center justify-between gap-3">
                      <div className="truncate text-xs text-slate-500">
                        {formatCompactNumber(chat.messageCount)} сообщений
                        {displaySender ? ` • ${displaySender}` : ""}
                      </div>
                      <div className="flex shrink-0 items-center gap-1 text-xs text-slate-500">
                        <Clock3 className="size-3" />
                        {formatRelativeTime(displayActivityAt)}
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
