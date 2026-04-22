import { BrainCircuit, MessageCircleHeart, RefreshCcw } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDateTime, stringifyUnknown } from "@/lib/format";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { MetricCard } from "@/components/system/MetricCard";
import { SectionCard } from "@/components/system/SectionCard";
import { WarningState } from "@/components/system/WarningState";

export function MemoryScreen() {
  const queryClient = useQueryClient();

  const memoryQuery = useQuery({
    queryKey: ["memory"],
    queryFn: () => api.memory(30),
    refetchInterval: 15_000,
  });

  const rebuildMutation = useMutation({
    mutationFn: () => api.rebuildMemory(),
    onSuccess: async (payload) => {
      toast.success(payload.message);
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось пересобрать память.");
    },
  });

  if (memoryQuery.isLoading) {
    return <LoadingState />;
  }

  if (memoryQuery.isError || !memoryQuery.data) {
    return (
      <WarningState
        title="Память не загрузилась"
        description={
          memoryQuery.error instanceof Error
            ? memoryQuery.error.message
            : "Не удалось получить memory overview."
        }
      />
    );
  }

  const memory = memoryQuery.data;

  return (
    <div className="flex flex-col gap-5">
      <SectionCard
        title="Memory layer"
        description="Память собирает короткие рабочие карты по чатам и людям, чтобы reply не опирался только на последние сообщения."
        action={
          <Button onClick={() => rebuildMutation.mutate()}>
            <RefreshCcw data-icon="inline-start" />
            Пересобрать память
          </Button>
        }
      >
        <div className="grid gap-4 lg:grid-cols-3">
          <MetricCard
            label="Карточки чатов"
            value={String(memory.summary.chatCards)}
            note="Локальные summary-карты по каждому активному контексту."
            icon={BrainCircuit}
          />
          <MetricCard
            label="Карточки людей"
            value={String(memory.summary.peopleCards)}
            note="Сигналы по людям и связанным open loops."
            icon={MessageCircleHeart}
          />
          <MetricCard
            label="Последняя пересборка"
            value={memory.summary.lastRebuildAt ? "есть" : "ещё не было"}
            note={formatDateTime(memory.summary.lastRebuildAt, true)}
            icon={RefreshCcw}
          />
        </div>
      </SectionCard>

      {memory.items.length === 0 ? (
        <EmptyState
          title="Память пока пустая"
          description="Сначала накопи сообщения или запусти rebuild после синхронизации нужных чатов."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {memory.items.map((item) => (
            <SectionCard
              key={item.id}
              title={item.chatTitle || `Chat #${item.chatId}`}
              description={item.currentState || "Без короткого описания состояния."}
              className="bg-black/14"
            >
              <div className="flex flex-col gap-4">
                <div className="text-sm leading-6 text-slate-300">
                  {item.summaryShort || "Короткое summary пока не собрано."}
                </div>
                {item.summaryLong ? (
                  <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-400">
                    {item.summaryLong}
                  </div>
                ) : null}
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                    <div className="mb-2 text-xs uppercase tracking-[0.22em] text-slate-500">Темы</div>
                    <div className="flex flex-col gap-2 text-sm leading-6 text-slate-300">
                      {item.topics.length ? item.topics.map((topic) => <div key={stringifyUnknown(topic)}>{stringifyUnknown(topic)}</div>) : <div>Нет явных тем</div>}
                    </div>
                  </div>
                  <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                    <div className="mb-2 text-xs uppercase tracking-[0.22em] text-slate-500">Что делать дальше</div>
                    <div className="flex flex-col gap-2 text-sm leading-6 text-slate-300">
                      {item.pendingTasks.length ? item.pendingTasks.map((task) => <div key={stringifyUnknown(task)}>{stringifyUnknown(task)}</div>) : <div>Открытых хвостов не видно</div>}
                    </div>
                  </div>
                </div>
                <div className="text-xs uppercase tracking-[0.2em] text-slate-500">
                  Обновлено: {formatDateTime(item.updatedAt)}
                </div>
              </div>
            </SectionCard>
          ))}
        </div>
      )}
    </div>
  );
}
