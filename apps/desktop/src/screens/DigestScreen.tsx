import { useState } from "react";
import { Newspaper, RefreshCcw, SendToBack } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { MetricCard } from "@/components/system/MetricCard";
import { SectionCard } from "@/components/system/SectionCard";
import { WarningState } from "@/components/system/WarningState";

export function DigestScreen() {
  const queryClient = useQueryClient();
  const [targetReference, setTargetReference] = useState("");
  const [targetLabel, setTargetLabel] = useState("");

  const digestQuery = useQuery({
    queryKey: ["digest"],
    queryFn: () => api.digest(8),
    refetchInterval: 15_000,
  });

  const [lastRun, setLastRun] = useState<Awaited<ReturnType<typeof api.runDigest>> | null>(null);

  const runDigestMutation = useMutation({
    mutationFn: (window: string) =>
      api.runDigest({
        window,
        use_provider_improvement: false,
      }),
    onSuccess: async (payload) => {
      setLastRun(payload);
      toast.success(payload.summaryShort || "Дайджест собран.");
      await queryClient.invalidateQueries();
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
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить target.");
    },
  });

  if (digestQuery.isLoading) {
    return <LoadingState />;
  }

  if (digestQuery.isError || !digestQuery.data) {
    return (
      <WarningState
        title="Digest overview не загрузился"
        description={
          digestQuery.error instanceof Error
            ? digestQuery.error.message
            : "Не удалось получить состояние дайджестов."
        }
      />
    );
  }

  const digest = digestQuery.data;
  const latest = digest.latest;

  return (
    <div className="flex flex-col gap-5">
      <SectionCard
        title="Дайджесты"
        description="Собранные сводки читаются как normal product output, а не как сырые debug-данные."
      >
        <div className="grid gap-4 lg:grid-cols-3">
          <MetricCard
            label="Target"
            value={digest.target.label || "не задан"}
            note={digest.target.chatType || "Сначала выбери канал или чат для доставки."}
            icon={SendToBack}
          />
          <MetricCard
            label="Последний запуск"
            value={latest ? "есть" : "ещё не было"}
            note={formatDateTime(latest?.createdAt || null)}
            icon={Newspaper}
          />
          <MetricCard
            label="Последний диапазон"
            value={lastRun?.window || "24h"}
            note={lastRun?.llmRefineApplied ? `LLM refine: ${lastRun.llmRefineProvider || "да"}` : "Deterministic baseline"}
            icon={RefreshCcw}
          />
        </div>
      </SectionCard>

      <SectionCard
        title="Быстрый запуск"
        description="Дайджест можно прогнать руками на 12 или 24 часа и сразу посмотреть результат."
        action={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => runDigestMutation.mutate("12h")}>
              12h
            </Button>
            <Button onClick={() => runDigestMutation.mutate("24h")}>24h</Button>
          </div>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="rounded-[24px] border border-white/7 bg-black/12 p-4">
            {latest ? (
              <div className="flex flex-col gap-4">
                <div className="text-lg font-semibold tracking-tight text-white">
                  {latest.summaryShort || "Короткой сводки пока нет"}
                </div>
                <div className="text-sm leading-7 text-slate-300">
                  {latest.summaryLong || "Подробная сводка пока не сохранена."}
                </div>
                <div className="flex flex-col gap-3">
                  {latest.items.map((item) => (
                    <div key={item.id} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                      <div className="text-sm font-medium text-white">{item.title || item.sourceChatTitle || "Источник"}</div>
                      <div className="mt-1 text-sm leading-6 text-slate-400">{item.summary || "Без summary"}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState
                title="Готовых дайджестов пока нет"
                description="Запусти 12h или 24h, чтобы получить первую читаемую сводку."
              />
            )}
          </div>

          <div className="rounded-[24px] border border-white/7 bg-black/12 p-4">
            <div className="mb-3 text-sm font-medium text-white">Target для доставки</div>
            <div className="flex flex-col gap-3">
              <Input
                className="border-white/8 bg-black/16 text-slate-100 placeholder:text-slate-500"
                placeholder="@username или chat_id"
                value={targetReference}
                onChange={(event) => setTargetReference(event.currentTarget.value)}
              />
              <Input
                className="border-white/8 bg-black/16 text-slate-100 placeholder:text-slate-500"
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
        </div>
      </SectionCard>

      {digest.recentRuns.length > 0 ? (
        <SectionCard
          title="Последние запуски"
          description="История последних сохранённых дайджестов."
        >
          <div className="grid gap-3">
            {digest.recentRuns.map((item) => (
              <div key={item.id} className="rounded-[20px] border border-white/6 bg-white/[0.03] px-4 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-sm font-medium text-white">{item.summaryShort || "Без короткой сводки"}</div>
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-500">
                    {formatDateTime(item.createdAt)}
                  </div>
                </div>
                <div className="mt-2 text-sm leading-6 text-slate-400">{item.summaryLong || "Подробной сводки нет."}</div>
              </div>
            ))}
          </div>
        </SectionCard>
      ) : null}
    </div>
  );
}
