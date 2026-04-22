import { useMemo } from "react";
import {
  ChevronDown,
  Copy,
  RefreshCcw,
  Send,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatConfidence, stringifyUnknown } from "@/lib/format";
import type { ReplyPreviewPayload } from "@/lib/types";

import { EmptyState } from "./EmptyState";
import { WarningState } from "./WarningState";

interface ReplyPanelProps {
  reply: ReplyPreviewPayload | null;
  loading?: boolean;
  onRefresh: () => void;
  onCopy: (text: string) => void;
}

function ActionButton({
  label,
  disabled,
  reason,
  onClick,
}: {
  label: string;
  disabled?: boolean;
  reason?: string | null;
  onClick?: () => void;
}) {
  const button = (
    <Button
      variant="outline"
      className="justify-start border-white/8 bg-black/14 text-slate-100"
      disabled={disabled}
      onClick={onClick}
    >
      {label}
    </Button>
  );

  if (!disabled || !reason) {
    return button;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span>{button}</span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}

export function ReplyPanel({
  reply,
  loading = false,
  onRefresh,
  onCopy,
}: ReplyPanelProps) {
  const suggestion = reply?.suggestion;
  const primaryReply = useMemo(() => {
    if (!suggestion) {
      return "";
    }
    return suggestion.finalReplyMessages.join("\n\n") || suggestion.replyText || "";
  }, [suggestion]);

  const alternativeReplies = useMemo(() => {
    if (!suggestion) {
      return [];
    }
    return suggestion.replyMessages.filter((item) => item && item !== primaryReply).slice(0, 3);
  }, [primaryReply, suggestion]);

  if (loading && !reply) {
    return (
      <div className="flex h-full items-center justify-center rounded-[28px] border border-white/7 bg-white/[0.03] text-sm text-slate-400">
        Собираю reply preview…
      </div>
    );
  }

  if (!reply) {
    return (
      <EmptyState
        title="Панель Astra готова"
        description="Выбери чат и Astra покажет фокус ответа, причину и предложенный вариант."
      />
    );
  }

  if (!suggestion) {
    return (
      <WarningState
        title="Ответ пока не собран"
        description={reply.errorMessage || "Astra не смогла предложить reply для выбранного контекста."}
        action={
          <div>
            <Button variant="outline" onClick={onRefresh}>
              <RefreshCcw data-icon="inline-start" />
              Повторить
            </Button>
          </div>
        }
      />
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 rounded-[28px] border border-white/7 bg-white/[0.03] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-2">
          <div className="text-lg font-semibold tracking-tight text-white">Панель Astra</div>
          <div className="text-sm leading-6 text-slate-400">
            Фокус строится по незакрытому триггеру из свежего окна контекста.
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon-sm" onClick={onRefresh}>
            <RefreshCcw />
          </Button>
          <Button onClick={() => onCopy(primaryReply)}>
            <Copy data-icon="inline-start" />
            Скопировать
          </Button>
        </div>
      </div>

      <div className="rounded-[22px] border border-cyan-300/10 bg-cyan-400/8 p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium text-cyan-100">
          <Sparkles />
          Фокус ответа
        </div>
        <div className="text-xl font-semibold tracking-tight text-white">
          {suggestion.focusLabel || "Нормальный рабочий ответ"}
        </div>
        <div className="mt-2 text-sm leading-6 text-cyan-50/80">
          {suggestion.focusReason || suggestion.reasonShort || "Astra держит открытый контекст и снимает зависший хвост."}
        </div>
      </div>

      <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-sm font-medium text-white">Предложенный ответ</div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
              уверенность {formatConfidence(suggestion.confidence)}
            </Badge>
            <Badge variant="outline" className="border-0 bg-amber-300/10 text-amber-100 ring-1 ring-amber-300/10">
              риск {suggestion.riskLabel || "под контролем"}
            </Badge>
          </div>
        </div>
        <div className="whitespace-pre-wrap text-[15px] leading-7 text-slate-50">
          {primaryReply || "Astra пока не предложила текст ответа."}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <ActionButton label="Короткий" disabled={!reply.actions.variants.short} reason={reply.actions.disabledReason} />
        <ActionButton label="Нормальный" onClick={onRefresh} />
        <ActionButton label="Мягче" disabled={!reply.actions.variants.softer} reason={reply.actions.disabledReason} />
        <ActionButton label="Жёстче" disabled={!reply.actions.variants.harder} reason={reply.actions.disabledReason} />
        <ActionButton label="В моём стиле" disabled={!reply.actions.variants.myStyle} reason={reply.actions.disabledReason} />
        <ActionButton label="Вставить в Telegram" disabled={!reply.actions.pasteToTelegram} reason={reply.actions.disabledReason} />
      </div>

      {alternativeReplies.length > 0 ? (
        <div className="rounded-[22px] border border-white/8 bg-black/14 p-4">
          <div className="mb-3 text-sm font-medium text-white">Альтернативы</div>
          <div className="flex flex-col gap-3">
            {alternativeReplies.map((item) => (
              <button
                key={item}
                type="button"
                className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-left text-sm leading-6 text-slate-200 transition-colors hover:border-cyan-300/10 hover:bg-cyan-400/6"
                onClick={() => onCopy(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="rounded-[22px] border border-white/8 bg-black/14 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
          <ShieldAlert />
          Почему именно такой фокус
        </div>
        <div className="text-sm leading-6 text-slate-300">
          {suggestion.reasonShort || suggestion.focusReason || "Astra выбирает спокойный вариант, который закрывает незавершённый вопрос."}
        </div>
        {reply.sourceSenderName || reply.sourceMessagePreview ? (
          <>
            <Separator className="my-4 bg-white/8" />
            <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Опорный триггер</div>
            <div className="mt-2 text-sm leading-6 text-slate-300">
              {reply.sourceSenderName ? `${reply.sourceSenderName}: ` : ""}
              {reply.sourceMessagePreview || "Без текста"}
            </div>
          </>
        ) : null}
      </div>

      <Collapsible className="rounded-[22px] border border-white/8 bg-black/14">
        <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 px-4 py-4 text-left text-sm font-medium text-white">
          Краткая техсводка
          <ChevronDown />
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t border-white/8 px-4 py-4">
          <div className="flex flex-col gap-3 text-sm leading-6 text-slate-300">
            <div>Стратегия: {suggestion.strategy || "deterministic"}</div>
            <div>Style source: {suggestion.styleSource || "без override"}</div>
            <div>Persona: {suggestion.personaApplied ? "применена" : "не применялась"}</div>
            <div>Few-shot: {suggestion.fewShotFound ? `найдено ${suggestion.fewShotMatchCount}` : "не использовались"}</div>
            <div>LLM refine: {suggestion.llmRefineApplied ? suggestion.llmRefineProvider || "включён" : "нет"}</div>
            {suggestion.styleNotes.length > 0 ? (
              <div>Style notes: {suggestion.styleNotes.join(" • ")}</div>
            ) : null}
            {suggestion.personaNotes.length > 0 ? (
              <div>Persona notes: {suggestion.personaNotes.join(" • ")}</div>
            ) : null}
            {suggestion.guardrailFlags.length > 0 ? (
              <div>Guardrails: {suggestion.guardrailFlags.join(" • ")}</div>
            ) : null}
            {suggestion.fewShotNotes.length > 0 ? (
              <div>Few-shot notes: {suggestion.fewShotNotes.join(" • ")}</div>
            ) : null}
            {suggestion.alternativeAction ? <div>Alternative action: {suggestion.alternativeAction}</div> : null}
            {suggestion.situation ? <div>Situation: {suggestion.situation}</div> : null}
            {suggestion.llmRefineNotes.length > 0 ? (
              <div>LLM notes: {suggestion.llmRefineNotes.map(stringifyUnknown).join(" • ")}</div>
            ) : null}
          </div>
        </CollapsibleContent>
      </Collapsible>

      <Button
        variant="outline"
        className="border-white/8 bg-black/14 text-slate-300"
        disabled={!reply.actions.markSent}
      >
        <Send data-icon="inline-start" />
        Пометить как отправленный
      </Button>
    </div>
  );
}
