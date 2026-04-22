import { useState } from "react";
import { Plus, RefreshCcw } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatDateTime, formatRelativeTime } from "@/lib/format";

import { EmptyState } from "@/components/system/EmptyState";
import { LoadingState } from "@/components/system/LoadingState";
import { SectionCard } from "@/components/system/SectionCard";
import { WarningState } from "@/components/system/WarningState";

export function SourcesScreen() {
  const queryClient = useQueryClient();
  const [reference, setReference] = useState("");
  const [title, setTitle] = useState("");
  const [chatType, setChatType] = useState("group");

  const sourcesQuery = useQuery({
    queryKey: ["sources"],
    queryFn: api.sources,
    refetchInterval: 12_000,
  });

  const mutateSource = useMutation<unknown, Error, { type: "enable" | "disable" | "sync"; chatId: number }>({
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
    onSuccess: async () => {
      toast.success("Источник обновлён.");
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

  return (
    <div className="flex flex-col gap-5">
      <SectionCard
        title="Управление источниками"
        description={sources.onboarding}
        action={
          <Button variant="outline" onClick={() => queryClient.invalidateQueries({ queryKey: ["sources"] })}>
            <RefreshCcw data-icon="inline-start" />
            Освежить
          </Button>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="rounded-[24px] border border-white/7 bg-black/12 p-4">
            {sources.items.length === 0 ? (
              <EmptyState
                title="Источников пока нет"
                description="Добавь chat_id или @username, чтобы Astra начала видеть локальный контекст."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="border-white/8">
                    <TableHead className="text-slate-400">Источник</TableHead>
                    <TableHead className="text-slate-400">Тип</TableHead>
                    <TableHead className="text-slate-400">Сообщения</TableHead>
                    <TableHead className="text-slate-400">Последнее обновление</TableHead>
                    <TableHead className="text-right text-slate-400">Действия</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sources.items.map((item) => (
                    <TableRow key={item.id} className="border-white/6 hover:bg-white/[0.03]">
                      <TableCell className="whitespace-normal">
                        <div className="flex flex-col gap-1">
                          <div className="text-sm font-medium text-white">{item.title}</div>
                          <div className="text-xs text-slate-500">{item.reference}</div>
                        </div>
                      </TableCell>
                      <TableCell className="text-slate-300">
                        {item.type} • {item.enabled ? "включён" : "выключен"}
                      </TableCell>
                      <TableCell className="text-slate-300">{item.messageCount}</TableCell>
                      <TableCell className="whitespace-normal text-slate-400">
                        <div>{formatDateTime(item.lastMessageAt)}</div>
                        <div className="text-xs text-slate-500">{formatRelativeTime(item.lastMessageAt)}</div>
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" size="sm" onClick={() => mutateSource.mutate({ type: "sync", chatId: item.id })}>
                            Sync
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              mutateSource.mutate({
                                type: item.enabled ? "disable" : "enable",
                                chatId: item.id,
                              })
                            }
                          >
                            {item.enabled ? "Disable" : "Enable"}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>

          <div className="rounded-[24px] border border-white/7 bg-black/12 p-4">
            <div className="mb-3 text-sm font-medium text-white">Добавить вручную</div>
            <div className="flex flex-col gap-3">
              <Input
                className="border-white/8 bg-black/16 text-slate-100 placeholder:text-slate-500"
                placeholder="@username или chat_id"
                value={reference}
                onChange={(event) => setReference(event.currentTarget.value)}
              />
              <Input
                className="border-white/8 bg-black/16 text-slate-100 placeholder:text-slate-500"
                placeholder="Понятное название"
                value={title}
                onChange={(event) => setTitle(event.currentTarget.value)}
              />
              <Select value={chatType} onValueChange={setChatType}>
                <SelectTrigger className="w-full border-white/8 bg-black/16 text-slate-100">
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
        </div>
      </SectionCard>
    </div>
  );
}
