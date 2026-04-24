import { useEffect, useRef } from "react";
import {
  AlertCircle,
  ImageIcon,
  LoaderCircle,
  Pause,
  Play,
  RefreshCcw,
  Sparkles,
} from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { buildFreshnessCopy, buildLiveCopy, buildWorkspaceCopy, toneBadgeClasses, tonePanelClasses } from "@/lib/chat-ux";
import { formatDateTime, formatRelativeTime, initials } from "@/lib/format";
import { safeArray } from "@/lib/runtime-guards";
import type { ChatFreshnessPayload, ChatItem, LiveStatusPayload, MessageItem, WorkspaceStatusPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

import { EmptyState } from "./EmptyState";
import { WarningState } from "./WarningState";

interface MessageListProps {
  chat: ChatItem | null;
  messages: MessageItem[];
  loading?: boolean;
  refreshing?: boolean;
  fullaccessReady?: boolean;
  workspaceStatus?: WorkspaceStatusPayload | null;
  canLoadOlder?: boolean;
  loadingOlder?: boolean;
  lastUpdatedAt?: string | null;
  freshness?: ChatFreshnessPayload | null;
  live?: LiveStatusPayload | null;
  highlightMessageKey?: string | null;
  errorMessage?: string | null;
  onLoadOlder: () => void;
  onRefresh: () => void;
  onToggleLivePause: () => void;
  onClearLiveError: () => void;
  onSyncChat: () => void;
}

export function MessageList({
  chat,
  messages,
  loading = false,
  refreshing = false,
  fullaccessReady = false,
  workspaceStatus = null,
  canLoadOlder = false,
  loadingOlder = false,
  lastUpdatedAt = null,
  freshness = null,
  live = null,
  highlightMessageKey = null,
  errorMessage = null,
  onLoadOlder,
  onRefresh,
  onToggleLivePause,
  onClearLiveError,
  onSyncChat,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const scrollRootRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const lastScrollTargetRef = useRef<{ chatKey: string | null; messageKey: string | null }>({
    chatKey: null,
    messageKey: null,
  });
  const safeMessages = safeArray(messages);
  const latestMessageKey = safeMessages.length > 0 ? safeMessages[safeMessages.length - 1]?.messageKey ?? null : null;
  const displayActivityAt = chat?.rosterLastActivityAt || chat?.lastMessageAt || null;
  const workspaceReadable = Boolean(workspaceStatus?.availability.workspaceAvailable);
  const historyReadable = Boolean(workspaceStatus?.availability.historyReadable);
  const workspaceCopy = buildWorkspaceCopy(workspaceStatus);
  const freshnessCopy = buildFreshnessCopy(freshness, live, workspaceStatus);
  const liveCopy = buildLiveCopy(live);

  useEffect(() => {
    const previous = lastScrollTargetRef.current;
    const chatChanged = previous.chatKey !== (chat?.chatKey ?? null);
    const latestChanged = previous.messageKey !== latestMessageKey;
    lastScrollTargetRef.current = {
      chatKey: chat?.chatKey ?? null,
      messageKey: latestMessageKey,
    };
    if (loadingOlder || (!chatChanged && !latestChanged)) {
      return;
    }
    if (chatChanged || stickToBottomRef.current) {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [chat?.chatKey, latestMessageKey, loadingOlder]);

  const handleScrollCapture = () => {
    const viewport = scrollRootRef.current?.querySelector<HTMLElement>("[data-slot='scroll-area-viewport']");
    if (!viewport) {
      return;
    }
    const distanceToBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    stickToBottomRef.current = distanceToBottom < 96;
  };

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
        title="Чат недоступен"
        description={`Astra не смогла собрать ленту сообщений. ${errorMessage}`}
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
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[22px] border border-white/7 bg-white/[0.035]">
      <div className="border-b border-white/7 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Avatar className="size-10 border border-white/8 bg-white/[0.04]">
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
              <Badge variant="outline" className={cn("border-0 ring-1", toneBadgeClasses(workspaceCopy.tone))}>
                {workspaceCopy.label}
              </Badge>
              {live ? (
                <Badge
                  variant="outline"
                  className={cn("border-0 ring-1", toneBadgeClasses(liveCopy.tone))}
                >
                  {liveCopy.label}
                </Badge>
              ) : null}
              {chat.unreadCount > 0 ? (
                <Badge variant="outline" className="border-0 bg-cyan-400/12 text-cyan-100 ring-1 ring-cyan-300/15">
                  {chat.unreadCount} непрочит.
                </Badge>
              ) : null}
              {chat.lastDirection === "inbound" ? (
                <Badge variant="outline" className="border-0 bg-rose-400/12 text-rose-100 ring-1 ring-rose-300/15">
                  Нужен ответ
                </Badge>
              ) : null}
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-400">
              <span>Последняя активность {formatRelativeTime(displayActivityAt)}</span>
              <span>{formatCompactMessageCount(chat.messageCount)}</span>
              <span>{lastUpdatedAt ? `обновлено ${formatDateTime(lastUpdatedAt)}` : "только открылся"}</span>
              <span className={cn(freshnessCopy.tone === "danger" && "text-rose-200", freshnessCopy.tone === "warning" && "text-amber-100")}>
                {freshnessCopy.label}
              </span>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            <Button
              variant="outline"
              className="border-white/8 bg-black/18 text-slate-100"
              onClick={onToggleLivePause}
              disabled={refreshing}
            >
              {live?.paused ? <Play data-icon="inline-start" /> : <Pause data-icon="inline-start" />}
              {live?.paused ? "Продолжить" : "Пауза"}
            </Button>
            <Button
              variant="outline"
              className="border-white/8 bg-black/18 text-slate-100"
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
              {refreshing ? "Обновляю" : "Обновить"}
            </Button>
            <Button
              variant="outline"
              className="border-white/8 bg-black/18 text-slate-100"
              onClick={onSyncChat}
              disabled={!fullaccessReady || refreshing}
            >
              <Sparkles data-icon="inline-start" />
              Синхронизировать
            </Button>
            {live?.lastError ? (
              <Button
                variant="outline"
                className="border-rose-300/14 bg-rose-400/8 text-rose-50"
                onClick={onClearLiveError}
              >
                <AlertCircle data-icon="inline-start" />
                Сбросить ошибку
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      {workspaceStatus?.degraded || live?.paused || live?.lastError ? (
        <div className={cn("mx-4 mt-3 rounded-[18px] border px-4 py-3 text-sm leading-6 text-slate-100", tonePanelClasses(freshnessCopy.tone))}>
          <div className="font-medium">{freshnessCopy.label}</div>
          <div className="text-xs text-slate-300">{freshnessCopy.detail}</div>
        </div>
      ) : null}

      <div ref={scrollRootRef} className="min-h-0 flex-1">
      <ScrollArea className="h-full min-h-0" onScrollCapture={handleScrollCapture}>
        <div className="flex flex-col gap-2 px-4 py-4">
          {canLoadOlder ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                className="border-white/8 bg-black/18 text-slate-100"
                onClick={onLoadOlder}
                disabled={loadingOlder}
              >
                {loadingOlder ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
                {loadingOlder ? "Загружаю" : "Показать ранние"}
              </Button>
            </div>
          ) : null}

          {loading && safeMessages.length === 0 ? <MessageListSkeleton /> : null}

          {!loading && safeMessages.length === 0 && !workspaceReadable ? (
            <EmptyState
              title="Чат пока нельзя прочитать"
              description="Astra видит чат в списке, но история сейчас недоступна. Обнови чат или проверь авторизацию Telegram runtime."
              action={
                <Button variant="outline" className="border-white/8 bg-black/18 text-slate-100" onClick={onRefresh}>
                  <RefreshCcw data-icon="inline-start" />
                  Обновить чат
                </Button>
              }
            />
          ) : null}

          {!loading && safeMessages.length === 0 && workspaceReadable && !historyReadable ? (
            <EmptyState
              title="История временно нечитабельна"
              description="Контекст собран, но ленту сообщений прочитать не удалось. Обнови чат или проверь Telegram runtime."
            />
          ) : null}

          {!loading && safeMessages.length === 0 && workspaceReadable && historyReadable ? (
            <EmptyState
              title="Сообщений пока нет"
              description="В выбранном чате нет доступной истории. Когда придут сообщения, они появятся здесь как обычная лента."
            />
          ) : null}

          {safeMessages.map((message, index) => {
            const inbound = message.direction === "inbound";
            const previousMessage = safeMessages[index - 1];
            const nextMessage = safeMessages[index + 1];
            const groupedWithPrevious = Boolean(previousMessage && previousMessage.direction === message.direction);
            const groupedWithNext = Boolean(nextMessage && nextMessage.direction === message.direction);
            const isHighlighted = Boolean(highlightMessageKey && message.messageKey === highlightMessageKey);

            return (
              <div
                key={message.messageKey}
                className={cn(
                  "flex w-full gap-2",
                  inbound ? "justify-start" : "justify-end",
                  groupedWithPrevious ? "pt-0.5" : "pt-3",
                )}
              >
                {inbound && !groupedWithPrevious ? (
                  <Avatar className="mt-1 size-8 border border-white/8 bg-white/[0.04]">
                    <AvatarFallback className="bg-white/8 text-slate-200">
                      {initials(message.senderName)}
                    </AvatarFallback>
                  </Avatar>
                ) : inbound ? (
                  <div className="w-8 shrink-0" />
                ) : null}

                <div
                  className={cn(
                    "max-w-[76%] rounded-[18px] border px-3.5 py-2.5 shadow-[0_12px_35px_rgba(3,8,18,0.16)]",
                    inbound
                      ? "border-white/8 bg-white/[0.045] text-slate-100"
                      : "border-cyan-300/14 bg-cyan-400/10 text-cyan-50",
                    groupedWithPrevious && inbound && "rounded-tl-md",
                    groupedWithPrevious && !inbound && "rounded-tr-md",
                    groupedWithNext && inbound && "rounded-bl-md",
                    groupedWithNext && !inbound && "rounded-br-md",
                    isHighlighted && "border-amber-200/35 bg-amber-300/10 shadow-[0_0_0_1px_rgba(251,191,36,0.18)]",
                  )}
                >
                  {!groupedWithPrevious ? (
                    <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
                      {message.senderName ? (
                        <span className={cn("font-medium", inbound ? "text-slate-300" : "text-cyan-100")}>
                          {inbound ? message.senderName : "Я"}
                        </span>
                      ) : (
                        <span className={cn("font-medium", inbound ? "text-slate-300" : "text-cyan-100")}>
                          {inbound ? "Входящее" : "Я"}
                        </span>
                      )}
                      <span className="text-slate-500">{formatDateTime(message.sentAt)}</span>
                      {isHighlighted ? (
                        <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15">
                          опорный сигнал
                        </Badge>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="whitespace-pre-wrap text-sm leading-5">
                    {message.text || "Без текста"}
                  </div>

                  {message.replyToMessageKey || message.replyToRuntimeMessageId ? (
                    <div className="mt-3 rounded-[16px] border border-white/6 bg-black/18 px-3 py-2 text-xs leading-5 text-slate-300">
                      Ответ на сообщение {message.replyToRuntimeMessageId || message.replyToMessageKey}
                    </div>
                  ) : null}

                  {message.mediaPreviewUrl ? (
                    <div className="mt-3 overflow-hidden rounded-[18px] border border-white/8 bg-black/20">
                      <img
                        src={message.mediaPreviewUrl}
                        alt={message.mediaType || "вложение"}
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

                {!inbound && !groupedWithPrevious ? (
                  <Avatar className="mt-1 size-8 border border-cyan-300/14 bg-cyan-400/10">
                    <AvatarFallback className="bg-cyan-400/12 text-cyan-100">Я</AvatarFallback>
                  </Avatar>
                ) : !inbound ? (
                  <div className="w-8 shrink-0" />
                ) : null}
              </div>
            );
          })}
          <div ref={endRef} />
        </div>
      </ScrollArea>
      </div>
    </section>
  );
}

function formatCompactMessageCount(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value) + " сообщений";
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
