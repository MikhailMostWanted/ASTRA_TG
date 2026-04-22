import { useMemo } from "react";
import {
  Bot,
  Database,
  MessagesSquare,
  RefreshCw,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useAppStore } from "@/stores/app-store";

import { LoadingState } from "@/components/system/LoadingState";
import { MetricCard } from "@/components/system/MetricCard";
import { SectionCard } from "@/components/system/SectionCard";
import { StatusCard } from "@/components/system/StatusCard";
import { SuccessState } from "@/components/system/SuccessState";
import { WarningState } from "@/components/system/WarningState";

const chartConfig = {
  value: {
    label: "Сигналы",
    color: "var(--color-chart-1)",
  },
};

export function DashboardScreen() {
  const queryClient = useQueryClient();
  const setActiveScreen = useAppStore((state) => state.setActiveScreen);

  const dashboardQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    refetchInterval: 10_000,
  });

  const operationMutation = useMutation({
    mutationFn: ({ action }: { action: string }) => api.runOperation(action),
    onSuccess: async (payload) => {
      toast.success(`Операция «${payload.action}» выполнена.`);
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Операция не выполнена.");
    },
  });

  const memoryMutation = useMutation({
    mutationFn: () => api.rebuildMemory(),
    onSuccess: async (payload) => {
      toast.success(payload.message);
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось пересобрать память.");
    },
  });

  const digestMutation = useMutation({
    mutationFn: () => api.runDigest({ window: "24h", use_provider_improvement: false }),
    onSuccess: async (payload) => {
      toast.success(payload.summaryShort || "Дайджест пересобран.");
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось запустить дайджест.");
    },
  });

  const chartData = useMemo(() => {
    const data = dashboardQuery.data;
    if (!data) {
      return [];
    }

    const onlineProcesses = data.processes.filter((item) => item.running).length;
    const visibleErrors = data.errors.filter((item) => item.tone !== "success").length;

    return [
      { label: "Готово", value: data.summary.readyChecks },
      { label: "Шаги", value: data.summary.nextSteps.length },
      { label: "Процессы", value: onlineProcesses },
      { label: "Ошибки", value: visibleErrors },
    ];
  }, [dashboardQuery.data]);

  if (dashboardQuery.isLoading) {
    return <LoadingState />;
  }

  if (dashboardQuery.isError || !dashboardQuery.data) {
    return (
      <WarningState
        title="Сводка не загрузилась"
        description={
          dashboardQuery.error instanceof Error
            ? dashboardQuery.error.message
            : "Не удалось получить состояние Astra."
        }
        action={
          <div>
            <Button variant="outline" onClick={() => dashboardQuery.refetch()}>
              <RefreshCw data-icon="inline-start" />
              Повторить
            </Button>
          </div>
        }
      />
    );
  }

  const dashboard = dashboardQuery.data;

  const handleQuickAction = (actionId: string) => {
    switch (actionId) {
      case "start":
      case "stop":
      case "restart":
        operationMutation.mutate({ action: actionId });
        return;
      case "refresh":
        queryClient.invalidateQueries();
        toast.success("Состояние обновлено.");
        return;
      case "memory":
        memoryMutation.mutate();
        return;
      case "digest":
        digestMutation.mutate();
        return;
      case "sync":
        setActiveScreen("sources");
        toast.message("Открыл экран источников: для sync нужен конкретный чат.");
        return;
      default:
        return;
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <SectionCard
        title="Операционный обзор"
        description="Здесь видно, в каком состоянии Astra, что уже готово и какой следующий полезный шаг лучше сделать."
        action={
          <div className="flex flex-wrap gap-2">
            {dashboard.quickActions.map((action) => (
              <Button
                key={action.id}
                variant={action.kind === "primary" ? "default" : action.kind === "secondary" ? "secondary" : "outline"}
                disabled={!action.enabled}
                onClick={() => handleQuickAction(action.id)}
              >
                {action.label}
              </Button>
            ))}
          </div>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.9fr)]">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <MetricCard
              label="Готовность"
              value={`${dashboard.summary.readyChecks}/${dashboard.summary.totalChecks}`}
              note="Проверки operational-контура."
              icon={Bot}
            />
            <MetricCard
              label="База"
              value={dashboard.database.available ? "доступна" : "недоступна"}
              note={dashboard.database.sqlitePath || dashboard.database.detail}
              icon={Database}
            />
            <MetricCard
              label="Provider"
              value={dashboard.providerApi.providerName || "deterministic"}
              note={dashboard.providerApi.reason || "Refine включается только когда реально нужен."}
              icon={MessagesSquare}
            />
          </div>

          <SectionCard
            title="Astra сейчас делает"
            description="Короткая человеческая сводка без debug-шума."
            className="bg-black/14"
          >
            <div className="flex flex-col gap-3">
              {dashboard.astraNow.map((item) => (
                <div key={item} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-200">
                  {item}
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
      </SectionCard>

      <div className="grid gap-4 xl:grid-cols-3">
        {dashboard.statusCards.map((item) => (
          <StatusCard key={item.key} item={item} />
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.9fr)]">
        <SectionCard
          title="Последние события"
          description="Что в системе произошло недавно."
        >
          <div className="flex flex-col gap-3">
            {dashboard.activity.map((item) => (
              <div key={`${item.title}-${item.timestamp}`} className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-sm font-medium text-white">{item.title}</div>
                  <div className="text-xs uppercase tracking-[0.22em] text-slate-500">
                    {formatDateTime(item.timestamp)}
                  </div>
                </div>
                <div className="mt-2 text-sm leading-6 text-slate-400">{item.detail || "Без деталей"}</div>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard
          title="Операционный пульс"
          description="Быстрый снимок по готовности, шагам и видимым проблемам."
          className="bg-black/14"
        >
          <ChartContainer className="h-[260px] w-full" config={chartConfig}>
            <BarChart data={chartData} margin={{ left: 0, right: 0, top: 16, bottom: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar dataKey="value" fill="var(--color-value)" radius={16} />
            </BarChart>
          </ChartContainer>
        </SectionCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
        <SectionCard
          title="Что требует внимания"
          description="Следующие шаги и предупреждения, которые реально важны."
        >
          <div className="flex flex-col gap-3">
            {dashboard.attention.map((item, index) => (
              <div
                key={`${item.text}-${index}`}
                className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-200"
              >
                {item.text}
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard
          title="Последние ошибки и warnings"
          description="Критичные сигналы вынесены отдельно, чтобы не ловить их в хвостах логов."
        >
          <div className="flex flex-col gap-3">
            {dashboard.errors.some((item) => item.tone !== "success") ? (
              dashboard.errors.map((item) => (
                <div
                  key={`${item.title}-${item.text}`}
                  className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3"
                >
                  <div className="text-sm font-medium text-white">{item.title}</div>
                  <div className="mt-1 text-sm leading-6 text-slate-400">{item.text}</div>
                </div>
              ))
            ) : (
              <SuccessState
                title="Критичных ошибок сейчас не видно"
                description="Bridge не видит свежих operational-проблем, которые требуют немедленного вмешательства."
              />
            )}
          </div>
        </SectionCard>
      </div>

      <SectionCard
        title="Managed processes"
        description="Bot и worker остаются прежними, desktop лишь аккуратно управляет ими."
      >
        <div className="grid gap-3 lg:grid-cols-2">
          {dashboard.processes.map((process) => (
            <div key={process.component} className="rounded-[20px] border border-white/6 bg-black/12 px-4 py-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium text-white">{process.component}</div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => operationMutation.mutate({ action: process.running ? "restart" : "start" })}
                >
                  {process.running ? "Restart" : "Start"}
                </Button>
              </div>
              <div className="mt-2 text-sm leading-6 text-slate-400">{process.detail}</div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                <div>PID: {process.pid || "—"}</div>
                <div>Лог: {process.logPath}</div>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
