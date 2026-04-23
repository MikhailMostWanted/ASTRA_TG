import { type ReactNode, useMemo, useState } from "react";
import { Newspaper, RefreshCcw, SendToBack } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api } from "@/lib/api";
import { formatCompactNumber, formatDateTime, formatRelativeTime } from "@/lib/format";
import { safeArray } from "@/lib/runtime-guards";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { WarningState } from "@/components/system/WarningState";

export function DigestScreen() {
  const queryClient = useQueryClient();
  const [targetReference, setTargetReference] = useState("");
  const [targetLabel, setTargetLabel] = useState("");
  const [lastRun, setLastRun] = useState<Awaited<ReturnType<typeof api.runDigest>> | null>(null);

  const digestQuery = useQuery({
    queryKey: ["digest"],
    queryFn: () => api.digest(8),
    refetchInterval: 15_000,
  });

  const sourcesQuery = useQuery({
    queryKey: ["sources"],
    queryFn: api.sources,
    refetchInterval: 15_000,
  });

  const runDigestMutation = useMutation({
    mutationFn: (window: string) =>
      api.runDigest({
        window,
      }),
    onSuccess: async (payload) => {
      setLastRun(payload);
      toast.success(payload.summaryShort || "Дайджест собран.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["digest"] }),
        queryClient.invalidateQueries({ queryKey: ["sources"] }),
      ]);
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось запустить дайджест.");
    },
  });

  const targetMutation = useMutation({
    mutationFn: () =>
      api.setDigestTarget({
        reference: targetReference || undefined,
        label: targetLabel || undefined,
      }),
    onSuccess: async (payload) => {
      toast.success(payload.message);
      setTargetReference("");
      setTargetLabel("");
      await queryClient.invalidateQueries({ queryKey: ["digest"] });
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить target.");
    },
  });

  const activeSources = useMemo(
    () =>
      safeArray(sourcesQuery.data?.items).filter(
        (item) => item.enabled && item.excludeFromDigest === false,
      ),
    [sourcesQuery.data?.items],
  );

  if (digestQuery.isLoading || sourcesQuery.isLoading) {
    return <LoadingState />;
  }

  if (digestQuery.isError || !digestQuery.data || sourcesQuery.isError || !sourcesQuery.data) {
    return (
      <WarningState
        title="Digest overview не загрузился"
        description="Не удалось собрать связку digest + source roster. Проверь локальный bridge и источник данных."
      />
    );
  }

  const digest = digestQuery.data;
  const target = digest.target || { label: null, chatType: null };
  const latest = digest.latest || null;
  const latestItems = safeArray(latest?.items);
  const recentRuns = safeArray(digest.recentRuns);
  const previewChunks = safeArray(lastRun?.previewChunks);
  const generation = lastRun
    ? {
        mode: lastRun.llmDebug?.mode
          || (lastRun.llmRefineApplied
            ? "llm_refine"
            : lastRun.llmRefineRequested
              ? "fallback"
              : "deterministic"),
        label: lastRun.llmRefineApplied
          ? "LLM-улучшение"
          : lastRun.llmDebug?.mode === "rejected_by_guardrails"
            ? "Отклонён guardrails"
          : lastRun.llmRefineRequested
            ? "Откат"
            : "Детерминированный",
        provider: lastRun.llmRefineProvider,
        notes: lastRun.llmRefineNotes,
        debug: lastRun.llmDebug,
      }
    : digest.generation;

  return (
    <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[minmax(0,1.08fr)_360px]">
      <section className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Digest output</div>
              <div className="text-base font-semibold text-white">Сводка по новостям и событиям</div>
              <div className="mt-1 text-sm leading-6 text-slate-400">
                Здесь виден последний runnable результат и история запусков, а не просто формальный факт существования digest.
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="border-white/8 bg-black/18 text-slate-100"
                onClick={() => runDigestMutation.mutate("12h")}
                disabled={runDigestMutation.isPending}
              >
                12h
              </Button>
              <Button onClick={() => runDigestMutation.mutate("24h")} disabled={runDigestMutation.isPending}>
                {runDigestMutation.isPending ? <RefreshCcw data-icon="inline-start" className="animate-spin" /> : null}
                24h
              </Button>
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <MiniDigestStat
              label="Target"
              value={target.label || "не задан"}
              note={target.chatType || "Сначала выбери канал или чат для доставки."}
              icon={<SendToBack className="size-4" />}
            />
            <MiniDigestStat
              label="Последний запуск"
              value={latest ? "есть" : "ещё не было"}
              note={
                generation
                  ? `${generation.label}${generation.provider ? ` • ${generation.provider}` : ""}`
                  : formatDateTime(latest?.createdAt || null)
              }
              icon={<Newspaper className="size-4" />}
            />
            <MiniDigestStat
              label="Активных sources"
              value={formatCompactNumber(activeSources.length)}
              note={lastRun ? `${lastRun.messageCount} сообщений в последнем окне` : "Источник данных для текущего окна"}
              icon={<RefreshCcw className="size-4" />}
            />
          </div>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-4 px-4 py-4">
            {latest ? (
              <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="text-sm font-medium text-white">Последний сохранённый digest</div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                      {formatDateTime(latest.createdAt)}
                    </Badge>
                    {generation ? (
                      <Badge
                        variant="outline"
                        className={
                          generation.mode === "llm_refine"
                            ? "border-0 bg-emerald-300/12 text-emerald-100 ring-1 ring-emerald-300/15"
                            : generation.mode === "rejected_by_guardrails"
                              ? "border-0 bg-rose-400/12 text-rose-100 ring-1 ring-rose-300/15"
                            : generation.mode === "fallback"
                              ? "border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15"
                              : "border-0 bg-white/7 text-slate-200 ring-1 ring-white/10"
                        }
                      >
                        {generation.label}
                      </Badge>
                    ) : null}
                  </div>
                </div>
                <div className="mt-4 text-2xl font-semibold tracking-tight text-white">
                  {latest.summaryShort || "Короткой сводки пока нет"}
                </div>
                <div className="mt-3 text-sm leading-7 text-slate-300">
                  {latest.summaryLong || "Подробная сводка пока не сохранена."}
                </div>
                {generation?.notes?.length ? (
                  <div className="mt-3 text-sm leading-6 text-slate-400">{generation.notes.join(" • ")}</div>
                ) : null}

                <div className="mt-4 flex flex-col gap-3">
                  {latestItems.map((item) => (
                    <div key={item.id} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                      <div className="text-sm font-medium text-white">
                        {item.title || item.sourceChatTitle || "Источник"}
                      </div>
                      <div className="mt-1 text-sm leading-6 text-slate-400">
                        {item.summary || "Без summary"}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState
                title="Готовых дайджестов пока нет"
                description="Запусти 12h или 24h, чтобы получить первую рабочую сводку и проверить source roster."
              />
            )}

            {previewChunks.length ? (
              <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
                <div className="text-sm font-medium text-white">Последний предпросмотр запуска</div>
                <div className="mt-3 flex flex-col gap-3">
                  {previewChunks.map((chunk) => (
                    <div key={chunk} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-300">
                      {chunk}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {recentRuns.length > 0 ? (
              <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
                <div className="text-sm font-medium text-white">История запусков</div>
                <div className="mt-3 flex flex-col gap-3">
                  {recentRuns.map((item) => (
                    <div key={item.id} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium text-white">{item.summaryShort || "Без короткой сводки"}</div>
                        <div className="text-xs text-slate-500">{formatDateTime(item.createdAt)}</div>
                      </div>
                      <div className="mt-2 text-sm leading-6 text-slate-400">
                        {item.summaryLong || "Подробной сводки нет."}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </ScrollArea>
      </section>

      <section className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-4">
          <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Control rail</div>
          <div className="text-base font-semibold text-white">Target и источники</div>
          <div className="mt-1 text-sm leading-6 text-slate-400">
            Понятно, откуда берётся digest и куда он должен уходить.
          </div>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-4 px-4 py-4">
            <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
              <div className="text-sm font-medium text-white">Target для доставки</div>
              <div className="mt-3 flex flex-col gap-3">
                <Input
                  className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
                  placeholder="@username или chat_id"
                  value={targetReference}
                  onChange={(event) => setTargetReference(event.currentTarget.value)}
                />
                <Input
                  className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
                  placeholder="Короткий label"
                  value={targetLabel}
                  onChange={(event) => setTargetLabel(event.currentTarget.value)}
                />
                <Button
                  disabled={!targetReference.trim() && !targetLabel.trim()}
                  onClick={() => targetMutation.mutate()}
                >
                  Сохранить target
                </Button>
              </div>
            </div>

            <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
              <div className="text-sm font-medium text-white">Активные источники в digest</div>
              <div className="mt-3 flex flex-col gap-3">
                {activeSources.length === 0 ? (
                  <EmptyState
                    title="Нет активных источников"
                    description="Пока нечего агрегировать. Сначала включи источники на соседнем экране."
                  />
                ) : null}

                {activeSources.map((item) => (
                  <div key={item.id} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium text-white">{item.title}</div>
                      <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                        {item.type}
                      </Badge>
                    </div>
                    <div className="mt-2 text-sm leading-6 text-slate-400">
                      {item.lastMessagePreview}
                    </div>
                    <div className="mt-2 text-xs text-slate-500">
                      {formatCompactNumber(item.messageCount)} сообщений • {formatRelativeTime(item.lastMessageAt)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </ScrollArea>
      </section>
    </div>
  );
}

function MiniDigestStat({
  label,
  value,
  note,
  icon,
}: {
  label: string;
  value: string;
  note: string;
  icon: ReactNode;
}) {
  return (
    <div className="rounded-[20px] border border-white/6 bg-white/[0.03] px-4 py-3">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-xl font-semibold tracking-tight text-white">{value}</div>
      <div className="mt-2 text-sm leading-6 text-slate-400">{note}</div>
    </div>
  );
}
