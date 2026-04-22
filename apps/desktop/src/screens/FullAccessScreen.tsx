import { useState } from "react";
import { CheckCheck, KeyRound, LogOut, ShieldCheck } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatCompactNumber } from "@/lib/format";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { MetricCard } from "@/components/system/MetricCard";
import { SectionCard } from "@/components/system/SectionCard";
import { WarningState } from "@/components/system/WarningState";

export function FullAccessScreen() {
  const queryClient = useQueryClient();
  const [manualReference, setManualReference] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");

  const overviewQuery = useQuery({
    queryKey: ["fullaccess"],
    queryFn: api.fullaccess,
    refetchInterval: 10_000,
  });

  const chatsQuery = useQuery({
    queryKey: ["fullaccess-chats"],
    queryFn: () => api.fullaccessChats(50),
    enabled: Boolean(overviewQuery.data?.status.enabled),
  });

  const requestCodeMutation = useMutation({
    mutationFn: api.requestFullaccessCode,
    onSuccess: async (payload) => {
      toast.success(payload.instructions[0] || "Код запрошен.");
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось запросить код.");
    },
  });

  const loginMutation = useMutation({
    mutationFn: () =>
      api.loginFullaccess({
        code,
        password: password || undefined,
      }),
    onSuccess: async (payload) => {
      toast.success(payload.instructions[0] || "Вход завершён.");
      setCode("");
      setPassword("");
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось завершить вход.");
    },
  });

  const logoutMutation = useMutation({
    mutationFn: api.logoutFullaccess,
    onSuccess: async () => {
      toast.success("Локальная full-access session очищена.");
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось выйти из full-access.");
    },
  });

  const syncMutation = useMutation({
    mutationFn: (reference: string) => api.syncFullaccessChat(reference),
    onSuccess: async (payload) => {
      toast.success(`Синхронизирован чат ${payload.chat.title}.`);
      setManualReference("");
      await queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось синхронизировать чат.");
    },
  });

  if (overviewQuery.isLoading) {
    return <LoadingState />;
  }

  if (overviewQuery.isError || !overviewQuery.data) {
    return (
      <WarningState
        title="Full-access не загрузился"
        description={
          overviewQuery.error instanceof Error
            ? overviewQuery.error.message
            : "Не удалось получить состояние full-access."
        }
      />
    );
  }

  const overview = overviewQuery.data;
  const status = overview.status;

  return (
    <div className="flex flex-col gap-5">
      <SectionCard
        title="Локальный full-access"
        description={overview.onboarding}
        action={
          <div className="flex gap-2">
            <Sheet>
              <SheetTrigger asChild>
                <Button>
                  <KeyRound data-icon="inline-start" />
                  Открыть локальный вход
                </Button>
              </SheetTrigger>
              <SheetContent side="right" className="border-l border-white/8 bg-[rgba(8,12,24,0.98)] text-white sm:max-w-lg">
                <SheetHeader>
                  <SheetTitle>Локальный login flow</SheetTitle>
                  <SheetDescription className="text-slate-400">
                    Код входа живёт только здесь или в CLI. Через Telegram-бот его передавать нельзя.
                  </SheetDescription>
                </SheetHeader>
                <div className="flex flex-col gap-4 px-4 pb-6">
                  <div className="rounded-[20px] border border-white/7 bg-white/[0.03] p-4 text-sm leading-6 text-slate-300">
                    {overview.instructions.join(" ")}
                  </div>
                  <div className="rounded-[20px] border border-cyan-300/12 bg-cyan-400/8 p-4 text-sm leading-6 text-cyan-50">
                    CLI fallback: <span className="font-mono">{overview.localLoginCommand}</span>
                  </div>
                  <Button onClick={() => requestCodeMutation.mutate()} disabled={!status.enabled}>
                    <ShieldCheck data-icon="inline-start" />
                    Запросить код
                  </Button>
                  <Input
                    className="border-white/8 bg-black/20 text-slate-100 placeholder:text-slate-500"
                    placeholder="Код из Telegram"
                    value={code}
                    onChange={(event) => setCode(event.currentTarget.value)}
                  />
                  <Input
                    className="border-white/8 bg-black/20 text-slate-100 placeholder:text-slate-500"
                    placeholder="Пароль 2FA, если нужен"
                    value={password}
                    onChange={(event) => setPassword(event.currentTarget.value)}
                  />
                  <Button disabled={!code.trim()} onClick={() => loginMutation.mutate()}>
                    <CheckCheck data-icon="inline-start" />
                    Завершить вход
                  </Button>
                </div>
              </SheetContent>
            </Sheet>
            <Button variant="outline" onClick={() => logoutMutation.mutate()} disabled={!status.sessionExists}>
              <LogOut data-icon="inline-start" />
              Logout
            </Button>
          </div>
        }
      >
        <div className="grid gap-4 lg:grid-cols-4">
          <MetricCard
            label="Статус"
            value={status.authorized ? "авторизован" : status.pendingLogin ? "ждёт код" : "не вошёл"}
            note={status.reason || "Слой работает локально и в read-only режиме."}
            icon={ShieldCheck}
          />
          <MetricCard
            label="Read-only"
            value={status.effectiveReadonly ? "да" : "нет"}
            note={`Запрошено: ${status.requestedReadonly ? "да" : "нет"}`}
            icon={KeyRound}
          />
          <MetricCard
            label="Синхронизировано чатов"
            value={formatCompactNumber(status.syncedChatCount)}
            note={`Сообщений: ${formatCompactNumber(status.syncedMessageCount)}`}
            icon={CheckCheck}
          />
          <MetricCard
            label="Session path"
            value={status.sessionExists ? "найден" : "не найден"}
            note={status.sessionPath}
            icon={LogOut}
          />
        </div>
      </SectionCard>

      <SectionCard
        title="Ручная синхронизация чата"
        description="Можно подтянуть один конкретный чат по @username или chat_id без бота."
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="rounded-[24px] border border-white/7 bg-black/12 p-4">
            {chatsQuery.data?.items?.length ? (
              <Table>
                <TableHeader>
                  <TableRow className="border-white/8">
                    <TableHead className="text-slate-400">Чат</TableHead>
                    <TableHead className="text-slate-400">Тип</TableHead>
                    <TableHead className="text-right text-slate-400">Sync</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {chatsQuery.data.items.map((item) => (
                    <TableRow key={item.reference} className="border-white/6 hover:bg-white/[0.03]">
                      <TableCell className="whitespace-normal">
                        <div className="flex flex-col gap-1">
                          <div className="text-sm font-medium text-white">{item.title}</div>
                          <div className="text-xs text-slate-500">{item.reference}</div>
                        </div>
                      </TableCell>
                      <TableCell className="text-slate-300">{item.chatType}</TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <Button variant="outline" size="sm" onClick={() => syncMutation.mutate(item.reference)}>
                            Sync
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState
                title="Список чатов пока пуст"
                description="Сначала проверь авторизацию и запроси список доступных чатов."
              />
            )}
          </div>

          <div className="rounded-[24px] border border-white/7 bg-black/12 p-4">
            <div className="mb-3 text-sm font-medium text-white">Sync по ссылке</div>
            <div className="flex flex-col gap-3">
              <Input
                className="border-white/8 bg-black/16 text-slate-100 placeholder:text-slate-500"
                placeholder="@username или chat_id"
                value={manualReference}
                onChange={(event) => setManualReference(event.currentTarget.value)}
              />
              <Button disabled={!manualReference.trim()} onClick={() => syncMutation.mutate(manualReference)}>
                Синхронизировать чат
              </Button>
              <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-400">
                Telethon доступен: {status.telethonAvailable ? "да" : "нет"}.
                <br />
                Лимит ручного sync: {status.syncLimit}.
              </div>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
