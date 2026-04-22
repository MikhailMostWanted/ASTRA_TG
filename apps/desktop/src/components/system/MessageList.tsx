import { motion } from "framer-motion";
import { ArrowDownLeft, ArrowUpRight, RefreshCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatDateTime } from "@/lib/format";
import type { ChatItem, MessageItem } from "@/lib/types";
import { cn } from "@/lib/utils";

import { EmptyState } from "./EmptyState";

interface MessageListProps {
  chat: ChatItem | null;
  messages: MessageItem[];
  loading?: boolean;
  onRefresh: () => void;
}

export function MessageList({
  chat,
  messages,
  loading = false,
  onRefresh,
}: MessageListProps) {
  if (!chat) {
    return (
      <EmptyState
        title="Выбери чат слева"
        description="Здесь появится живая лента сообщений и свежий контекст для ответа."
      />
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 rounded-[28px] border border-white/7 bg-white/[0.03] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <div className="truncate text-lg font-semibold tracking-tight text-white">{chat.title}</div>
            <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
              {chat.reference}
            </Badge>
            <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/10">
              {chat.syncStatus}
            </Badge>
          </div>
          <div className="text-sm leading-6 text-slate-400">
            Ответ строится по свежему окну контекста, а не только по последней реплике.
          </div>
        </div>
        <Button variant="outline" onClick={onRefresh}>
          <RefreshCcw data-icon="inline-start" />
          Обновить контекст
        </Button>
      </div>

      <ScrollArea className="min-h-0 flex-1 rounded-[24px] border border-white/6 bg-black/12 px-4 py-4">
        {loading && messages.length === 0 ? (
          <div className="text-sm text-slate-400">Подтягиваю сообщения…</div>
        ) : null}

        {!loading && messages.length === 0 ? (
          <EmptyState
            title="Сообщений пока нет"
            description="Когда в выбранный чат придут данные, Astra покажет их здесь."
          />
        ) : null}

        <div className="flex flex-col gap-3">
          {messages.map((message, index) => {
            const inbound = message.direction === "inbound";

            return (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.24, delay: index * 0.01 }}
                className={cn("flex w-full", inbound ? "justify-start" : "justify-end")}
              >
                <div
                  className={cn(
                    "max-w-[82%] rounded-[22px] border px-4 py-3 shadow-[0_12px_35px_rgba(3,8,18,0.18)]",
                    inbound
                      ? "border-white/8 bg-white/[0.045] text-slate-100"
                      : "border-cyan-300/12 bg-cyan-400/10 text-cyan-50",
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
                  <div className="whitespace-pre-wrap text-sm leading-6">{message.text || "Без текста"}</div>
                  {message.hasMedia ? (
                    <div className="mt-2 text-xs text-slate-500">
                      Медиа: {message.mediaType || "вложение"}
                    </div>
                  ) : null}
                </div>
              </motion.div>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
