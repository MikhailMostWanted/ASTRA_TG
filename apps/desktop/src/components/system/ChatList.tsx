import { Star, RefreshCcw, Search, Pin } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatCompactNumber, formatRelativeTime, initials } from "@/lib/format";
import type { ChatItem } from "@/lib/types";
import { cn } from "@/lib/utils";

import { EmptyState } from "./EmptyState";

interface ChatListProps {
  chats: ChatItem[];
  selectedChatId: number | null;
  search: string;
  filter: string;
  sort: string;
  favorites: number[];
  loading?: boolean;
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
  empty: "пусто",
};

export function ChatList({
  chats,
  selectedChatId,
  search,
  filter,
  sort,
  favorites,
  loading = false,
  onSearchChange,
  onFilterChange,
  onSortChange,
  onSelectChat,
  onToggleFavorite,
  onRefresh,
}: ChatListProps) {
  return (
    <div className="flex h-full flex-col gap-4 rounded-[28px] border border-white/7 bg-white/[0.03] p-4">
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <div className="text-sm font-medium text-white">Чаты и каналы</div>
            <div className="text-sm text-slate-400">Поиск, сортировка и быстрый выбор рабочего контекста.</div>
          </div>
          <Button variant="outline" size="icon-sm" onClick={onRefresh}>
            <RefreshCcw />
          </Button>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <Input
            className="w-full border-white/8 bg-black/15 pl-10 text-slate-100 placeholder:text-slate-500"
            placeholder="Поиск по названию, @username или chat_id"
            value={search}
            onChange={(event) => onSearchChange(event.currentTarget.value)}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Select value={filter} onValueChange={onFilterChange}>
            <SelectTrigger className="w-full border-white/8 bg-black/15 text-slate-100">
              <SelectValue placeholder="Фильтр" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">Все</SelectItem>
                <SelectItem value="enabled">Только активные</SelectItem>
                <SelectItem value="reply">Где уже есть reply</SelectItem>
                <SelectItem value="fullaccess">Через full-access</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>

          <Select value={sort} onValueChange={onSortChange}>
            <SelectTrigger className="w-full border-white/8 bg-black/15 text-slate-100">
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
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2">
          {!loading && chats.length === 0 ? (
            <EmptyState
              title="Чаты пока не найдены"
              description="Проверь фильтры или подтяни источники на вкладке «Источники»."
            />
          ) : null}

          {chats.map((chat) => {
            const isSelected = chat.id === selectedChatId;
            const isFavorite = favorites.includes(chat.id);

            return (
              <button
                key={chat.id}
                type="button"
                className={cn(
                  "rounded-[22px] border border-transparent bg-transparent p-3 text-left transition-all hover:border-white/8 hover:bg-white/[0.04]",
                  isSelected && "border-cyan-300/12 bg-cyan-400/8 shadow-[0_10px_35px_rgba(8,145,178,0.1)]",
                )}
                onClick={() => onSelectChat(chat.id)}
              >
                <div className="flex items-start gap-3">
                  <Avatar className="size-11 border border-white/8 bg-white/[0.04]">
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
                          "rounded-full p-1 text-slate-500 transition-colors hover:bg-white/6 hover:text-white",
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
                        {chat.type}
                      </Badge>
                      <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/10">
                        {syncLabelMap[chat.syncStatus] || chat.syncStatus}
                      </Badge>
                      {chat.lastSourceAdapter ? (
                        <Badge variant="outline" className="border-0 bg-white/7 text-slate-300 ring-1 ring-white/10">
                          {chat.lastSourceAdapter}
                        </Badge>
                      ) : null}
                      {chat.isDigestTarget ? (
                        <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/10">
                          digest target
                        </Badge>
                      ) : null}
                    </div>

                    <div className="mt-3 line-clamp-2 text-sm leading-6 text-slate-300">
                      {chat.lastMessagePreview}
                    </div>

                    <div className="mt-3 flex items-center justify-between gap-3 text-xs text-slate-500">
                      <div className="truncate">
                        {formatCompactNumber(chat.messageCount)} сообщений
                        {chat.lastSenderName ? ` • ${chat.lastSenderName}` : ""}
                      </div>
                      <div className="shrink-0">{formatRelativeTime(chat.lastMessageAt)}</div>
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
