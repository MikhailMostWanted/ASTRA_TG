import { useState } from "react";
import { AlarmClock, RefreshCcw, ScanSearch } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api } from "@/lib/api";
import { formatDateTime, formatConfidence } from "@/lib/format";
import { extractErrorMessage, safeArray } from "@/lib/runtime-guards";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { MetricCard } from "@/components/system/MetricCard";
import { SectionCard } from "@/components/system/SectionCard";
import { WarningState } from "@/components/system/WarningState";

export function RemindersScreen() {
  const queryClient = useQueryClient();
  const [windowArgument, setWindowArgument] = useState("24h");
  const [sourceReference, setSourceReference] = useState("");

  const remindersQuery = useQuery({
    queryKey: ["reminders"],
    queryFn: api.reminders,
    refetchInterval: 15_000,
  });

  const scanMutation = useMutation({
    mutationFn: () =>
      api.scanReminders({
        window_argument: windowArgument,
        source_reference: sourceReference || undefined,
      }),
    onSuccess: async (payload) => {
      toast.success(payload.summaryText);
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось просканировать reminders.");
    },
  });

  if (remindersQuery.isLoading) {
    return <LoadingState />;
  }

  if (remindersQuery.isError || !remindersQuery.data) {
    return (
      <WarningState
        title="Reminders overview не загрузился"
        description={extractErrorMessage(remindersQuery.error, "Не удалось получить состояние reminders pipeline.")}
      />
    );
  }

  const reminders = remindersQuery.data;
  const summary = reminders.summary || {
    candidateCount: 0,
    confirmedTaskCount: 0,
    activeReminderCount: 0,
    lastNotificationAt: null,
  };
  const candidates = safeArray(reminders.candidates);
  const tasks = safeArray(reminders.tasks);
  const reminderItems = safeArray(reminders.reminders);

  return (
    <ScrollArea className="h-full min-h-0">
      <div className="flex flex-col gap-5 pr-2">
      <SectionCard
        title="Напоминания и задачи"
        description="Здесь видно, какие open loops уже замечены, что подтверждено и что скоро нужно вернуть в фокус."
      >
        <div className="grid gap-4 lg:grid-cols-4">
          <MetricCard
            label="Кандидаты"
            value={String(summary.candidateCount || 0)}
            note="Потенциальные задачи, найденные в переписке."
            icon={ScanSearch}
          />
          <MetricCard
            label="Подтверждено"
            value={String(summary.confirmedTaskCount || 0)}
            note="Активные задачи, за которыми уже следит pipeline."
            icon={AlarmClock}
          />
          <MetricCard
            label="Активные reminders"
            value={String(summary.activeReminderCount || 0)}
            note="Что ещё не закрыто."
            icon={RefreshCcw}
          />
          <MetricCard
            label="Последняя отправка"
            value={summary.lastNotificationAt ? "была" : "не было"}
            note={formatDateTime(summary.lastNotificationAt)}
            icon={AlarmClock}
          />
        </div>
      </SectionCard>

      <SectionCard
        title="Сканирование"
        description="Можно вручную прогнать reminders pipeline по окну времени или конкретному источнику."
        action={
          <Button onClick={() => scanMutation.mutate()}>
            <ScanSearch data-icon="inline-start" />
            Сканировать
          </Button>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
          <Input
            className="border-white/8 bg-black/16 text-slate-100 placeholder:text-slate-500"
            placeholder="Окно, например 24h"
            value={windowArgument}
            onChange={(event) => setWindowArgument(event.currentTarget.value)}
          />
          <Input
            className="border-white/8 bg-black/16 text-slate-100 placeholder:text-slate-500"
            placeholder="@username или chat_id, если нужен один источник"
            value={sourceReference}
            onChange={(event) => setSourceReference(event.currentTarget.value)}
          />
        </div>
      </SectionCard>

      <div className="grid gap-4 xl:grid-cols-3">
        <SectionCard
          title="Кандидаты"
          description="Что Astra нашла, но ещё не превратила в подтверждённые задачи."
        >
          <div className="flex flex-col gap-3">
            {candidates.length ? candidates.map((item) => (
              <div key={item.id} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                <div className="text-sm font-medium text-white">{item.title}</div>
                <div className="mt-1 text-sm leading-6 text-slate-400">{item.summary || "Без summary"}</div>
              </div>
            )) : <EmptyState title="Кандидатов нет" description="Сейчас новых напоминаний в переписке не видно." />}
          </div>
        </SectionCard>

        <SectionCard
          title="Активные задачи"
          description="Подтверждённые open loops по чатам."
        >
          <div className="flex flex-col gap-3">
            {tasks.length ? tasks.map((item) => (
              <div key={item.id} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                <div className="text-sm font-medium text-white">{item.title}</div>
                <div className="mt-1 text-sm leading-6 text-slate-400">{item.sourceChatTitle || "Без чата"}</div>
                <div className="mt-2 text-xs uppercase tracking-[0.2em] text-slate-500">
                  confidence {formatConfidence(item.confidence)} • due {formatDateTime(item.dueAt)}
                </div>
              </div>
            )) : <EmptyState title="Активных задач нет" description="Пока нечего держать в reminders pipeline." />}
          </div>
        </SectionCard>

        <SectionCard
          title="Активные reminders"
          description="Ближайшие напоминания, которые worker может доставить."
        >
          <div className="flex flex-col gap-3">
            {reminderItems.length ? reminderItems.map((item) => (
              <div key={item.id} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                <div className="text-sm font-medium text-white">{item.task?.title || "Reminder"}</div>
                <div className="mt-1 text-sm leading-6 text-slate-400">
                  {item.task?.sourceChatTitle || "Без owner chat"}
                </div>
                <div className="mt-2 text-xs uppercase tracking-[0.2em] text-slate-500">
                  remind at {formatDateTime(item.remindAt)}
                </div>
              </div>
            )) : <EmptyState title="Активных reminders нет" description="Пайплайн сейчас спокоен." />}
          </div>
        </SectionCard>
      </div>
      </div>
    </ScrollArea>
  );
}
