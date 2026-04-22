import { useDeferredValue, useMemo, useState } from "react";
import { Plus, RefreshCcw } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import { formatCompactNumber, formatDateTime, formatRelativeTime, initials } from "@/lib/format";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { WarningState } from "@/components/system/WarningState";

export function SourcesScreen() {
  const queryClient = useQueryClient();
  const [reference, setReference] = useState("");
  const [title, setTitle] = useState("");
  const [chatType, setChatType] = useState("group");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const sourcesQuery = useQuery({
    queryKey: ["sources"],
    queryFn: api.sources,
    refetchInterval: 12_000,
  });

  const fullaccessQuery = useQuery({
    queryKey: ["fullaccess"],
    queryFn: api.fullaccess,
    refetchInterval: 15_000,
  });

  const mutateSource = useMutation<unknown, Error, { type: "enable" | "disable" | "sync"; chatId: number; title: string }>({
    mutationFn: ({ type, chatId }: { type: "enable" | "disable" | "sync"; chatId: number }) => {
      switch (type) {
        case "enable":
          return api.enableSource(chatId);
        case "disable":
          return api.disableSource(chatId);
        case "sync":
          return api.syncSource(chatId);
      }
    },
    onSuccess: async (_, variables) => {
      const message = variables.type === "sync" ? `Источник «${variables.title}» синхронизирован.` : "Источник обновлён.";
      toast.success(message);
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить источник.");
    },
  });

  const addSourceMutation = useMutation({
    mutationFn: () =>
      api.addSource({
        reference,
        title,
        chat_type: chatType,
      }),
    onSuccess: async (payload) => {
      toast.success(payload.message);
      setReference("");
      setTitle("");
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось добавить источник.");
    },
  });

  const visibleSources = useMemo(() => {
    const items = sourcesQuery.data?.items || [];
    const query = deferredSearch.trim().toLowerCase();
    if (!query) {
      return items;
    }
    return items.filter((item) =>
      [item.title, item.reference, item.handle || "", item.type]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [deferredSearch, sourcesQuery.data?.items]);

  if (sourcesQuery.isLoading) {
    return <LoadingState />;
  }

  if (sourcesQuery.isError || !sourcesQuery.data) {
    return (
      <WarningState
        title="Источники не загрузились"
        description={
          sourcesQuery.error instanceof Error
            ? sourcesQuery.error.message
            : "Не удалось получить список источников."
        }
      />
    );
  }

  const sources = sourcesQuery.data;
  const activeCount = sources.items.filter((item) => item.enabled).length;
  const fullaccessCount = sources.items.filter((item) => item.syncStatus === "fullaccess").length;
  const readyForReplyCount = sources.items.filter((item) => item.type !== "channel" && item.lastDirection === "inbound").length;
  const withHistoryCount = sources.items.filter((item) => item.messageCount > 0).length;

  return (
    <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[minmax(0,1.12fr)_360px]">
      <section className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Source management</div>
              <div className="text-base font-semibold text-white">Источники и синхронизация</div>
              <div className="mt-1 text-sm leading-6 text-slate-400">{sources.onboarding}</div>
            </div>
            <Button
              variant="outline"
              className="border-white/8 bg-black/18 text-slate-100"
              onClick={() => queryClient.invalidateQueries({ queryKey: ["sources"] })}
            >
              <RefreshCcw data-icon="inline-start" />
              Освежить
            </Button>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MiniStat label="Всего" value={formatCompactNumber(sources.count)} />
            <MiniStat label="Активны" value={formatCompactNumber(activeCount)} />
            <MiniStat label="Через full-access" value={formatCompactNumber(fullaccessCount)} />
            <MiniStat label="С историей" value={formatCompactNumber(withHistoryCount)} />
          </div>

          <div className="mt-4">
            <Input
              className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
              placeholder="Поиск по имени, reference или типу"
              value={search}
              onChange={(event) => setSearch(event.currentTarget.value)}
            />
          </div>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-2 px-3 py-3">
            {visibleSources.length === 0 ? (
              <EmptyState
                title="Источники не найдены"
                description="Добавь новый source справа или смени поисковый запрос."
              />
            ) : null}

            {visibleSources.map((item) => (
              <div
                key={item.id}
                className="rounded-[24px] border border-white/6 bg-white/[0.03] px-4 py-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex min-w-0 items-start gap-3">
                    <Avatar className="size-11 border border-white/8 bg-white/[0.04]">
                      <AvatarImage src={item.avatarUrl || undefined} alt={item.title} />
                      <AvatarFallback className="bg-cyan-400/10 text-cyan-100">
                        {initials(item.title)}
                      </AvatarFallback>
                    </Avatar>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-white">{item.title}</div>
                      <div className="truncate text-xs text-slate-500">{item.reference}</div>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                          {item.type}
                        </Badge>
                        <Badge
                          variant="outline"
                          className={
                            item.enabled
                              ? "border-0 bg-emerald-300/12 text-emerald-100 ring-1 ring-emerald-300/15"
                              : "border-0 bg-white/7 text-slate-300 ring-1 ring-white/10"
                          }
                        >
                          {item.enabled ? "активен" : "выключен"}
                        </Badge>
                        <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/10">
                          {item.syncStatus}
                        </Badge>
                        {item.lastDirection === "inbound" && item.type !== "channel" ? (
                          <Badge variant="outline" className="border-0 bg-rose-400/12 text-rose-100 ring-1 ring-rose-300/15">
                            нужен ответ
                          </Badge>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  <div className="flex shrink-0 gap-2">
                    <Button
                      variant="outline"
                      className="border-white/8 bg-black/18 text-slate-100"
                      size="sm"
                      onClick={() =>
                        mutateSource.mutate({
                          type: "sync",
                          chatId: item.id,
                          title: item.title,
                        })
                      }
                      disabled={mutateSource.isPending || !fullaccessQuery.data?.status.readyForManualSync}
                    >
                      Sync
                    </Button>
                    <Button
                      variant="outline"
                      className="border-white/8 bg-black/18 text-slate-100"
                      size="sm"
                      onClick={() =>
                        mutateSource.mutate({
                          type: item.enabled ? "disable" : "enable",
                          chatId: item.id,
                          title: item.title,
                        })
                      }
                      disabled={mutateSource.isPending}
                    >
                      {item.enabled ? "Выключить" : "Включить"}
                    </Button>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 text-sm text-slate-400 sm:grid-cols-3">
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">История</div>
                    <div className="mt-1 text-white">{formatCompactNumber(item.messageCount)} сообщений</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Последний апдейт</div>
                    <div className="mt-1 text-white">{formatDateTime(item.lastMessageAt)}</div>
                    <div className="text-xs text-slate-500">{formatRelativeTime(item.lastMessageAt)}</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Последний фрагмент</div>
                    <div className="mt-1 line-clamp-2 text-sm leading-6 text-slate-300">{item.lastMessagePreview}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </section>

      <section className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-4">
          <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Control rail</div>
          <div className="text-base font-semibold text-white">Добавить источник</div>
          <div className="mt-1 text-sm leading-6 text-slate-400">
            Чем яснее source roster, тем понятнее digest, memory и reply.
          </div>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-4 px-4 py-4">
            <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
              <div className="text-sm font-medium text-white">Быстрый статус</div>
              <div className="mt-3 flex flex-col gap-3 text-sm leading-6 text-slate-300">
                <div>Активных источников: {activeCount}.</div>
                <div>Сигналов для reply прямо сейчас: {readyForReplyCount}.</div>
                <div>
                  Full-access sync: {fullaccessQuery.data?.status.readyForManualSync ? "доступен" : "ещё не готов"}.
                </div>
                <div>{fullaccessQuery.data?.status.reason || "Статус full-access недоступен."}</div>
              </div>
            </div>

            <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
              <div className="text-sm font-medium text-white">Новый источник</div>
              <div className="mt-3 flex flex-col gap-3">
                <Input
                  className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
                  placeholder="@username или chat_id"
                  value={reference}
                  onChange={(event) => setReference(event.currentTarget.value)}
                />
                <Input
                  className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
                  placeholder="Человекочитаемое название"
                  value={title}
                  onChange={(event) => setTitle(event.currentTarget.value)}
                />
                <Select value={chatType} onValueChange={setChatType}>
                  <SelectTrigger className="w-full border-white/8 bg-black/18 text-slate-100">
                    <SelectValue placeholder="Тип чата" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value="group">Группа</SelectItem>
                      <SelectItem value="channel">Канал</SelectItem>
                      <SelectItem value="private">Личный чат</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <Button
                  disabled={!reference.trim() || addSourceMutation.isPending}
                  onClick={() => addSourceMutation.mutate()}
                >
                  <Plus data-icon="inline-start" />
                  Добавить источник
                </Button>
              </div>
            </div>

            <div className="rounded-[24px] border border-amber-300/12 bg-amber-300/8 p-4 text-sm leading-6 text-amber-50">
              Если source добавлен, но sync не проходит, проблема обычно не в UI, а в состоянии full-access или reference. Теперь это видно сразу, без похода в терминал.
            </div>
          </div>
        </ScrollArea>
      </section>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] border border-white/6 bg-white/[0.03] px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">{label}</div>
      <div className="mt-2 text-xl font-semibold tracking-tight text-white">{value}</div>
    </div>
  );
}
