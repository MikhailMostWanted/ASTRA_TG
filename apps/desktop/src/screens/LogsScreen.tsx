import { useMemo, useState } from "react";
import {
  Archive,
  RefreshCcw,
  ShieldPlus,
  Stethoscope,
  TerminalSquare,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { formatDateTime, stringifyUnknown } from "@/lib/format";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { SectionCard } from "@/components/system/SectionCard";
import { SuccessState } from "@/components/system/SuccessState";
import { WarningState } from "@/components/system/WarningState";

const keywordMap: Record<string, string[]> = {
  provider: ["provider", "llm", "openai", "ollama", "refine"],
  fullaccess: ["fullaccess", "telethon", "session", "login"],
};

export function LogsScreen() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("all");

  const opsQuery = useQuery({
    queryKey: ["ops"],
    queryFn: () => api.ops(100),
    refetchInterval: 10_000,
  });

  const logsQuery = useQuery({
    queryKey: ["logs"],
    queryFn: () => api.logs(undefined, 140),
    refetchInterval: 10_000,
  });

  const [lastOperation, setLastOperation] = useState<Awaited<ReturnType<typeof api.runOperation>> | null>(null);

  const operationMutation = useMutation({
    mutationFn: (action: string) => api.runOperation(action),
    onSuccess: async (payload) => {
      setLastOperation(payload);
      toast.success(`Операция «${payload.action}» выполнена.`);
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Операция не выполнена.");
    },
  });

  const filteredLogs = useMemo(() => {
    const items = logsQuery.data?.items || [];
    if (filter === "all") {
      return items;
    }
    if (filter === "bot" || filter === "worker") {
      return items.filter((item) => item.component === filter);
    }

    const keywords = keywordMap[filter] || [];
    return items
      .map((item) => ({
        ...item,
        lines: item.lines.filter((line) =>
          keywords.some((keyword) => line.toLowerCase().includes(keyword)),
        ),
      }))
      .filter((item) => item.lines.length > 0);
  }, [filter, logsQuery.data?.items]);

  if (opsQuery.isLoading || logsQuery.isLoading) {
    return <LoadingState />;
  }

  if (opsQuery.isError || logsQuery.isError || !opsQuery.data || !logsQuery.data) {
    return (
      <WarningState
        title="Ops/logs пока не загрузились"
        description="Не удалось собрать operational-данные. Проверь локальный bridge и managed процессы."
      />
    );
  }

  const ops = opsQuery.data;

  return (
    <div className="flex flex-col gap-5">
      <SectionCard
        title="Ops panel"
        description="Сервисные операции собраны в нормальный интерфейс: без терминальной помойки, но с быстрым доступом к деталям."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => operationMutation.mutate("backup")}>
              <Archive data-icon="inline-start" />
              Backup
            </Button>
            <Button variant="outline" onClick={() => operationMutation.mutate("export")}>
              <ShieldPlus data-icon="inline-start" />
              Export
            </Button>
            <Button variant="outline" onClick={() => operationMutation.mutate("doctor")}>
              <Stethoscope data-icon="inline-start" />
              Doctor
            </Button>
            <Button
              variant="outline"
              onClick={async () => {
                await queryClient.invalidateQueries();
                toast.success("Статус обновлён.");
              }}
            >
              <RefreshCcw data-icon="inline-start" />
              Status
            </Button>
          </div>
        }
      >
        <div className="grid gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
          <div className="flex flex-col gap-4">
            <SectionCard
              title="Doctor"
              description="Что operational-слой считает нормальным, а что уже просит внимания."
              className="bg-black/14"
            >
              <div className="flex flex-col gap-3">
                {ops.doctor.warnings.length > 0 ? (
                  ops.doctor.warnings.map((item) => (
                    <div key={item} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-300">
                      {item}
                    </div>
                  ))
                ) : (
                  <SuccessState
                    title="Doctor не видит острых проблем"
                    description="Слой диагностики сейчас не выдаёт warning-ов, требующих срочного вмешательства."
                  />
                )}
              </div>
            </SectionCard>

            {lastOperation ? (
              <SectionCard
                title="Последняя операция"
                description={`Результат действия «${lastOperation.action}».`}
                className="bg-black/14"
              >
                <div className="flex flex-col gap-3 text-sm leading-6 text-slate-300">
                  {lastOperation.path ? <div>Путь: {lastOperation.path}</div> : null}
                  {lastOperation.sourcePath ? <div>Источник: {lastOperation.sourcePath}</div> : null}
                  {lastOperation.okItems?.length ? <div>OK: {lastOperation.okItems.join(" • ")}</div> : null}
                  {lastOperation.warnings?.length ? <div>Warnings: {lastOperation.warnings.join(" • ")}</div> : null}
                  {lastOperation.results?.length ? (
                    <div>
                      {lastOperation.results.map((item) => `${item.component}: ${item.detail}`).join(" • ")}
                    </div>
                  ) : null}
                  {lastOperation.startResults?.length ? (
                    <div>
                      Start: {lastOperation.startResults.map((item) => `${item.component}: ${item.detail}`).join(" • ")}
                    </div>
                  ) : null}
                  {lastOperation.stopResults?.length ? (
                    <div>
                      Stop: {lastOperation.stopResults.map((item) => `${item.component}: ${item.detail}`).join(" • ")}
                    </div>
                  ) : null}
                  {lastOperation.payload ? (
                    <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-xs leading-6 text-slate-400">
                      {stringifyUnknown(lastOperation.payload)}
                    </div>
                  ) : null}
                </div>
              </SectionCard>
            ) : null}
          </div>

          <SectionCard
            title="Process status"
            description="Managed bot/worker и их свежие operational details."
          >
            <div className="grid gap-3 md:grid-cols-2">
              {ops.processes.map((process) => (
                <div key={process.component} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-white">{process.component}</div>
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">
                      {process.running ? "online" : "offline"}
                    </div>
                  </div>
                  <div className="mt-2 text-sm leading-6 text-slate-400">{process.detail}</div>
                  <div className="mt-3 text-xs uppercase tracking-[0.2em] text-slate-500">
                    Лог: {process.logPath}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
      </SectionCard>

      <SectionCard
        title="Логи"
        description="Просмотр последних строк без ощущения терминала. Для provider/full-access фильтр ищет совпадения внутри bot/worker log stream."
        action={
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger className="w-[200px] border-white/8 bg-black/16 text-slate-100">
              <SelectValue placeholder="Фильтр" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">Все</SelectItem>
                <SelectItem value="bot">bot</SelectItem>
                <SelectItem value="worker">worker</SelectItem>
                <SelectItem value="provider">provider</SelectItem>
                <SelectItem value="fullaccess">full-access</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        }
      >
        <div className="flex flex-col gap-4">
          {filteredLogs.length ? (
            filteredLogs.map((item) => (
              <div key={`${item.component}-${filter}`} className="rounded-[22px] border border-white/6 bg-black/16 px-4 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-white">
                    <TerminalSquare />
                    {item.component}
                  </div>
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-500">
                    {formatDateTime(new Date().toISOString())}
                  </div>
                </div>
                <div className="mt-3 max-h-[320px] overflow-auto rounded-[18px] border border-white/6 bg-[#040812] px-4 py-4 font-mono text-xs leading-6 text-slate-300">
                  {item.lines.length ? item.lines.join("\n") : "Совпадений в хвосте логов пока нет."}
                </div>
              </div>
            ))
          ) : (
            <EmptyState
              title="Совпадений пока нет"
              description="Для выбранного фильтра в свежем хвосте логов пока не нашлось релевантных строк."
            />
          )}
        </div>
      </SectionCard>
    </div>
  );
}
