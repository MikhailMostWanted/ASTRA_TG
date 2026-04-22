import { useEffect, useRef } from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  ImageIcon,
  LoaderCircle,
  RefreshCcw,
  Sparkles,
} from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, formatRelativeTime, initials } from "@/lib/format";
import { safeArray } from "@/lib/runtime-guards";
import type { ChatFreshnessPayload, ChatItem, MessageItem } from "@/lib/types";
import { cn } from "@/lib/utils";

import { EmptyState } from "./EmptyState";
import { WarningState } from "./WarningState";

interface MessageListProps {
  chat: ChatItem | null;
  messages: MessageItem[];
  loading?: boolean;
  refreshing?: boolean;
  fullaccessReady?: boolean;
  lastUpdatedAt?: string | null;
  freshness?: ChatFreshnessPayload | null;
  errorMessage?: string | null;
  onRefresh: () => void;
  onSyncChat: () => void;
}

export function MessageList({
  chat,
  messages,
  loading = false,
  refreshing = false,
  fullaccessReady = false,
  lastUpdatedAt = null,
  freshness = null,
  errorMessage = null,
  onRefresh,
  onSyncChat,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const safeMessages = safeArray(messages);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [chat?.id, safeMessages.length]);

  if (!chat) {
    return (
      <EmptyState
        title="Выбери чат слева"
        description="Здесь появится живая лента сообщений, статус синхронизации и свежий хвост для ответа."
      />
    );
  }

  if (errorMessage) {
    return (
      <WarningState
        title="Лента сообщений не загрузилась"
        description={errorMessage}
        action={
          <div>
            <Button variant="outline" onClick={onRefresh}>
              <RefreshCcw data-icon="inline-start" />
              Повторить
            </Button>
          </div>
        }
      />
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
      <div className="border-b border-white/7 px-4 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <Avatar className="size-11 border border-white/8 bg-white/[0.04]">
                <AvatarImage src={chat.avatarUrl || undefined} alt={chat.title} />
                <AvatarFallback className="bg-cyan-400/10 text-cyan-100">
                  {initials(chat.title)}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <div className="truncate text-lg font-semibold tracking-tight text-white">{chat.title}</div>
                <div className="truncate text-sm text-slate-400">
                  {chat.handle ? `@${chat.handle}` : chat.reference}
                </div>
              </div>
              <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                {chat.type}
              </Badge>
              <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/10">
                {chat.syncStatus}
              </Badge>
              {chat.lastDirection === "inbound" ? (
                <Badge variant="outline" className="border-0 bg-rose-400/12 text-rose-100 ring-1 ring-rose-300/15">
                  Нужен ответ
                </Badge>
              ) : null}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-slate-400">
              <span>Последнее сообщение {formatRelativeTime(chat.lastMessageAt)}</span>
              <span>UI обновлён {lastUpdatedAt ? formatDateTime(lastUpdatedAt) : "только открылся"}</span>
              <span>{formatDateTime(chat.lastMessageAt)} • {chat.messageCount} сообщений</span>
              {freshness ? <span>{freshness.label}</span> : null}
            </div>
          </div>

          <div className="flex shrink-0 gap-2">
            <Button
              variant="outline"
              className="border-white/8 bg-black/18 text-slate-100"
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
              Обновить контекст
            </Button>
            <Button
              variant="outline"
              className="border-white/8 bg-black/18 text-slate-100"
              onClick={onSyncChat}
              disabled={!fullaccessReady || refreshing}
            >
              <Sparkles data-icon="inline-start" />
              Синхронизировать чат
            </Button>
          </div>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-4 px-4 py-4">
          {loading && safeMessages.length === 0 ? <MessageListSkeleton /> : null}

          {!loading && safeMessages.length === 0 ? (
            <EmptyState
              title="Сообщений пока нет"
              description="Когда в выбранный чат придут данные, здесь появится рабочая лента сообщений."
            />
          ) : null}

          {safeMessages.map((message, index) => {
            const inbound = message.direction === "inbound";

            return (
              <div
                key={message.id}
                className={cn(
                  "flex w-full gap-3",
                  inbound ? "justify-start" : "justify-end",
                  index > 0 && safeMessages[index - 1]?.direction === message.direction ? "pt-0" : "pt-1",
                )}
              >
                {inbound ? (
                  <Avatar className="mt-1 size-9 border border-white/8 bg-white/[0.04]">
                    <AvatarFallback className="bg-white/8 text-slate-200">
                      {initials(message.senderName)}
                    </AvatarFallback>
                  </Avatar>
                ) : null}

                <div
                  className={cn(
                    "max-w-[86%] rounded-[24px] border px-4 py-3 shadow-[0_12px_35px_rgba(3,8,18,0.18)]",
                    inbound
                      ? "border-white/8 bg-white/[0.045] text-slate-100"
                      : "border-cyan-300/14 bg-cyan-400/10 text-cyan-50",
                  )}
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                    <Badge
                      variant="outline"
                      className={cn(
                        "border-0 ring-1",
                        inbound
                          ? "bg-white/7 text-slate-300 ring-white/10"
                          : "bg-cyan-300/12 text-cyan-100 ring-cyan-300/12",
                      )}
                    >
                      {inbound ? <ArrowDownLeft data-icon="inline-start" /> : <ArrowUpRight data-icon="inline-start" />}
                      {inbound ? "входящее" : "исходящее"}
                    </Badge>
                    {message.senderName ? (
                      <span className="text-slate-400">{message.senderName}</span>
                    ) : null}
                    <span className="text-slate-500">{formatDateTime(message.sentAt)}</span>
                  </div>

                  <div className="whitespace-pre-wrap text-sm leading-6">
                    {message.text || "Без текста"}
                  </div>

                  {message.mediaPreviewUrl ? (
                    <div className="mt-3 overflow-hidden rounded-[18px] border border-white/8 bg-black/20">
                      <img
                        src={message.mediaPreviewUrl}
                        alt={message.mediaType || "media preview"}
                        className="max-h-[280px] w-full object-cover"
                      />
                    </div>
                  ) : null}

                  {message.hasMedia ? (
                    <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-white/8 bg-black/18 px-3 py-1 text-xs text-slate-300">
                      <ImageIcon className="size-3.5" />
                      {message.mediaType || "вложение"}
                    </div>
                  ) : null}
                </div>

                {!inbound ? (
                  <Avatar className="mt-1 size-9 border border-cyan-300/14 bg-cyan-400/10">
                    <AvatarFallback className="bg-cyan-400/12 text-cyan-100">Я</AvatarFallback>
                  </Avatar>
                ) : null}
              </div>
            );
          })}
          <div ref={endRef} />
        </div>
      </ScrollArea>
    </section>
  );
}

function MessageListSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      {Array.from({ length: 6 }).map((_, index) => (
        <div
          key={index}
          className={cn("flex gap-3", index % 2 === 0 ? "justify-start" : "justify-end")}
        >
          {index % 2 === 0 ? <Skeleton className="size-9 rounded-full bg-white/10" /> : null}
          <div className="w-[68%] rounded-[24px] border border-white/6 bg-white/[0.03] px-4 py-3">
            <Skeleton className="h-3 w-1/3 bg-white/10" />
            <Skeleton className="mt-3 h-3 w-full bg-white/10" />
            <Skeleton className="mt-2 h-3 w-4/5 bg-white/10" />
            <Skeleton className="mt-2 h-3 w-3/5 bg-white/10" />
          </div>
          {index % 2 === 1 ? <Skeleton className="size-9 rounded-full bg-white/10" /> : null}
        </div>
      ))}
    </div>
  );
}
