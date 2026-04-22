import { type ReactNode, useDeferredValue, useMemo, useState } from "react";
import {
  CheckCheck,
  KeyRound,
  LoaderCircle,
  LogOut,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatCompactNumber, initials } from "@/lib/format";
import { extractErrorMessage, safeArray } from "@/lib/runtime-guards";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { WarningState } from "@/components/system/WarningState";

export function FullAccessScreen() {
  const queryClient = useQueryClient();
  const [manualReference, setManualReference] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [chatSearch, setChatSearch] = useState("");
  const deferredChatSearch = useDeferredValue(chatSearch);

  const overviewQuery = useQuery({
    queryKey: ["fullaccess"],
    queryFn: api.fullaccess,
    refetchInterval: 10_000,
  });

  const status = overviewQuery.data?.status ?? {
    enabled: false,
    sessionExists: false,
    authorized: false,
    pendingLogin: false,
    effectiveReadonly: true,
    syncLimit: 0,
    syncedChatCount: 0,
    syncedMessageCount: 0,
    readyForManualSync: false,
    reason: "Статус full-access пока недоступен.",
    sessionPath: "—",
  };
  const chatsQuery = useQuery({
    queryKey: ["fullaccess-chats"],
    queryFn: () => api.fullaccessChats(50),
    enabled: Boolean(status?.readyForManualSync),
    refetchInterval: 20_000,
  });

  const requestCodeMutation = useMutation({
    mutationFn: api.requestFullaccessCode,
    onSuccess: async (payload) => {
      toast.success(payload.instructions[0] || "Код запрошен.");
      await queryClient.invalidateQueries({ queryKey: ["fullaccess"] });
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
      toast.success(payload.kind === "password_required" ? "Нужен пароль 2FA." : "Вход завершён.");
      if (payload.kind !== "password_required") {
        setCode("");
        setPassword("");
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["fullaccess"] }),
        queryClient.invalidateQueries({ queryKey: ["fullaccess-chats"] }),
      ]);
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось завершить вход.");
    },
  });

  const logoutMutation = useMutation({
    mutationFn: api.logoutFullaccess,
    onSuccess: async () => {
      toast.success("Локальная full-access session очищена.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["fullaccess"] }),
        queryClient.invalidateQueries({ queryKey: ["fullaccess-chats"] }),
        queryClient.invalidateQueries({ queryKey: ["chats"] }),
        queryClient.invalidateQueries({ queryKey: ["sources"] }),
      ]);
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
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["fullaccess"] }),
        queryClient.invalidateQueries({ queryKey: ["fullaccess-chats"] }),
        queryClient.invalidateQueries({ queryKey: ["chats"] }),
        queryClient.invalidateQueries({ queryKey: ["sources"] }),
        queryClient.invalidateQueries({ queryKey: ["chat-workspace"] }),
      ]);
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Не удалось синхронизировать чат.");
    },
  });

  const visibleChats = useMemo(() => {
    const items = safeArray(chatsQuery.data?.items);
    const query = deferredChatSearch.trim().toLowerCase();
    if (!query) {
      return items;
    }

    return items.filter((item) => {
      const haystack = [item.title, item.reference, item.username || "", item.chatType]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [chatsQuery.data?.items, deferredChatSearch]);

  if (overviewQuery.isLoading) {
    return <LoadingState />;
  }

  if (overviewQuery.isError || !overviewQuery.data) {
    return (
      <WarningState
        title="Full-access не загрузился"
        description={
          extractErrorMessage(overviewQuery.error, "Не удалось получить состояние full-access.")
        }
      />
    );
  }

  const overview = overviewQuery.data;
  const instructions = safeArray(overview.instructions).filter(
    (item): item is string => typeof item === "string" && item.trim().length > 0,
  );
  const readyLabel = status?.authorized
    ? "Сессия готова"
    : status?.pendingLogin
      ? "Ждёт код"
      : "Нужен вход";

  return (
    <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
      <section className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Desktop auth</div>
              <div className="text-base font-semibold text-white">Full-access без терминала</div>
              <div className="mt-1 text-sm leading-6 text-slate-400">
                {overview.onboarding || "Desktop-path для full-access авторизации и sync."}
              </div>
            </div>

            <div className="flex gap-2">
              <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/10">
                {readyLabel}
              </Badge>
              <Button
                variant="outline"
                className="border-white/8 bg-black/18 text-slate-100"
                onClick={() => logoutMutation.mutate()}
                disabled={!status?.sessionExists || logoutMutation.isPending}
              >
                {logoutMutation.isPending ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <LogOut data-icon="inline-start" />}
                Logout
              </Button>
            </div>
          </div>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-4 px-4 py-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <StatusMetric
                label="Авторизация"
                value={status?.authorized ? "готова" : status?.pendingLogin ? "код запрошен" : "не завершена"}
                note={status?.reason || "Статус недоступен"}
                icon={<ShieldCheck className="size-4" />}
              />
              <StatusMetric
                label="Read-only"
                value={status?.effectiveReadonly ? "да" : "нет"}
                note={`Sync limit: ${status?.syncLimit || 0}`}
                icon={<Sparkles className="size-4" />}
              />
              <StatusMetric
                label="Чатов в локальной базе"
                value={formatCompactNumber(status?.syncedChatCount || 0)}
                note={`Сообщений: ${formatCompactNumber(status?.syncedMessageCount || 0)}`}
                icon={<MessageSquareText className="size-4" />}
              />
              <StatusMetric
                label="Session"
                value={status?.sessionExists ? "найдена" : "нет"}
                note={status?.sessionPath || "—"}
                icon={<KeyRound className="size-4" />}
              />
            </div>

            <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
              <div className="text-sm font-medium text-white">Шаг 1. Запросить код</div>
              <div className="mt-1 text-sm leading-6 text-slate-400">
                Если `FULLACCESS_PHONE` и API credentials настроены, код прилетит в Telegram и останется внутри desktop flow.
              </div>
              <div className="mt-4">
                <Button
                  onClick={() => requestCodeMutation.mutate()}
                  disabled={!status?.enabled || requestCodeMutation.isPending}
                >
                  {requestCodeMutation.isPending ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <ShieldCheck data-icon="inline-start" />}
                  Запросить код
                </Button>
              </div>
            </div>

            <div className="rounded-[24px] border border-white/7 bg-black/16 p-4">
              <div className="text-sm font-medium text-white">Шаг 2. Ввести код и 2FA</div>
              <div className="mt-1 text-sm leading-6 text-slate-400">
                Код вводится прямо здесь. Если Telegram запросит пароль 2FA, просто добавь его в соседнее поле.
              </div>
              <div className="mt-4 grid gap-3">
                <Input
                  className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
                  placeholder="Код из Telegram"
                  value={code}
                  onChange={(event) => setCode(event.currentTarget.value)}
                />
                <Input
                  className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
                  placeholder="Пароль 2FA, если нужен"
                  value={password}
                  onChange={(event) => setPassword(event.currentTarget.value)}
                />
                <Button
                  className="justify-start"
                  disabled={!code.trim() || loginMutation.isPending}
                  onClick={() => loginMutation.mutate()}
                >
                  {loginMutation.isPending ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <CheckCheck data-icon="inline-start" />}
                  Завершить вход
                </Button>
              </div>
            </div>

            <div className="rounded-[24px] border border-amber-300/12 bg-amber-300/8 p-4 text-sm leading-6 text-amber-50">
              <div className="font-medium">CLI fallback остаётся резервным</div>
              <div className="mt-1">{instructions.join(" ") || "Если UI-path недоступен, можно использовать CLI fallback."}</div>
              <div className="mt-2 rounded-[18px] border border-white/8 bg-black/18 px-3 py-2 font-mono text-xs text-slate-100">
                {overview.localLoginCommand}
              </div>
            </div>
          </div>
        </ScrollArea>
      </section>

      <section className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Sync roster</div>
              <div className="text-base font-semibold text-white">Чаты для синхронизации</div>
              <div className="mt-1 text-sm leading-6 text-slate-400">
                После авторизации здесь доступны ручной sync по chat list или по точному reference.
              </div>
            </div>
            <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
              lim {status?.syncLimit}
            </Badge>
          </div>

          <div className="mt-4">
            <Input
              className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
              placeholder="Поиск по имени, reference или типу"
              value={chatSearch}
              onChange={(event) => setChatSearch(event.currentTarget.value)}
              disabled={!status?.readyForManualSync}
            />
          </div>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-2 px-3 py-3">
            {!status?.readyForManualSync ? (
              <EmptyState
                title="Сначала заверши вход"
                description={status?.reason || "Desktop ждёт авторизацию, прежде чем показывать чат-лист."}
              />
            ) : null}

            {status?.readyForManualSync && chatsQuery.isLoading ? <FullAccessChatSkeleton /> : null}

            {status?.readyForManualSync && !chatsQuery.isLoading && visibleChats.length === 0 ? (
              <EmptyState
                title="Подходящих чатов нет"
                description="Либо список ещё не подтянулся, либо поиск отфильтровал все результаты."
              />
            ) : null}

            {visibleChats.map((item) => (
              <div
                key={item.reference}
                className="flex items-center justify-between gap-3 rounded-[22px] border border-white/6 bg-white/[0.03] px-4 py-3"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <Avatar className="size-10 border border-white/8 bg-white/[0.04]">
                    <AvatarImage src={item.avatarUrl || undefined} alt={item.title} />
                    <AvatarFallback className="bg-cyan-400/10 text-cyan-100">
                      {initials(item.title)}
                    </AvatarFallback>
                  </Avatar>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-white">{item.title}</div>
                    <div className="truncate text-xs text-slate-500">{item.reference}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                    {item.chatType}
                  </Badge>
                  <Button
                    variant="outline"
                    className="border-white/8 bg-black/18 text-slate-100"
                    size="sm"
                    onClick={() => syncMutation.mutate(item.reference)}
                    disabled={syncMutation.isPending}
                  >
                    Sync
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>

        <div className="border-t border-white/7 px-4 py-4">
          <div className="text-sm font-medium text-white">Точный sync по reference</div>
          <div className="mt-1 text-sm leading-6 text-slate-400">
            Если нужный чат не попал в видимый список, укажи `@username` или `chat_id` вручную.
          </div>
          <div className="mt-3 flex gap-3">
            <Input
              className="border-white/8 bg-black/18 text-slate-100 placeholder:text-slate-500"
              placeholder="@username или chat_id"
              value={manualReference}
              onChange={(event) => setManualReference(event.currentTarget.value)}
              disabled={!status?.readyForManualSync}
            />
            <Button
              disabled={!manualReference.trim() || syncMutation.isPending || !status?.readyForManualSync}
              onClick={() => syncMutation.mutate(manualReference)}
            >
              {syncMutation.isPending ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <Sparkles data-icon="inline-start" />}
              Синхронизировать
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}

function StatusMetric({
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
    <div className="rounded-[22px] border border-white/6 bg-white/[0.03] px-4 py-4">
      <div className="flex items-center gap-2 text-sm font-medium text-white">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight text-white">{value}</div>
      <div className="mt-2 text-sm leading-6 text-slate-400">{note}</div>
    </div>
  );
}

function FullAccessChatSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: 7 }).map((_, index) => (
        <div key={index} className="flex items-center justify-between gap-3 rounded-[22px] border border-white/6 bg-white/[0.03] px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <Skeleton className="size-10 rounded-full bg-white/10" />
            <div className="space-y-2">
              <Skeleton className="h-4 w-48 bg-white/10" />
              <Skeleton className="h-3 w-32 bg-white/10" />
            </div>
          </div>
          <Skeleton className="h-8 w-20 rounded-xl bg-white/10" />
        </div>
      ))}
    </div>
  );
}
