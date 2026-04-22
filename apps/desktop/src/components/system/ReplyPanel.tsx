import { useEffect, useMemo, useState } from "react";
import {
  Bug,
  ChevronDown,
  ChevronUp,
  CheckCheck,
  Copy,
  DatabaseZap,
  LoaderCircle,
  RefreshCcw,
  Send,
  ShieldAlert,
  Sparkles,
  WandSparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatConfidence, formatDateTime, stringifyUnknown } from "@/lib/format";
import { normalizeReplyPreviewPayload } from "@/lib/runtime-guards";
import type { ChatFreshnessPayload, ReplyPreviewPayload } from "@/lib/types";
import { buildReplyDraftScopeKey, type ChatWorkspaceState } from "@/stores/app-store";
import { cn } from "@/lib/utils";

import { EmptyState } from "./EmptyState";
import { WarningState } from "./WarningState";

interface ReplyPanelProps {
  reply: ReplyPreviewPayload | null;
  freshness?: ChatFreshnessPayload | null;
  workflowState: ChatWorkspaceState | null;
  loading?: boolean;
  refreshing?: boolean;
  errorMessage?: string | null;
  onRefresh: () => void;
  onCopy: (text: string) => void;
  onUseDraft: (text: string, sourceMessageId: number | null) => void;
  onMarkSent: (sourceMessageId: number | null) => void;
  onClearDraft: () => void;
}

export function ReplyPanel({
  reply,
  freshness = null,
  workflowState,
  loading = false,
  refreshing = false,
  errorMessage = null,
  onRefresh,
  onCopy,
  onUseDraft,
  onMarkSent,
  onClearDraft,
}: ReplyPanelProps) {
  const safeReply = normalizeReplyPreviewPayload(reply);
  const suggestion = safeReply?.suggestion;
  const replyOptions = useMemo(() => {
    if (!suggestion) {
      return [];
    }

    if (suggestion.variants.length > 0) {
      return suggestion.variants;
    }

    return Array.from(
      new Set(
        [
          ...suggestion.finalReplyMessages,
          ...suggestion.replyMessages,
          suggestion.replyText,
          suggestion.baseReplyText,
        ].filter((item): item is string => Boolean(item && item.trim())),
      ),
    )
      .slice(0, 3)
      .map((text, index) => ({
        id: `fallback-${index}`,
        label: `Вариант ${index + 1}`,
        description: "Рабочий текст ответа.",
        text,
      }));
  }, [suggestion]);

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => {
    setSelectedIndex(0);
    setShowDebug(false);
  }, [suggestion?.sourceMessageId, suggestion?.replyText]);

  const selectedReply = replyOptions[selectedIndex]?.text || "";
  const selectedVariant = replyOptions[selectedIndex] || null;
  const llmDebug = suggestion?.llmDebug ?? null;
  const llmDecisionReason = llmDebug?.decisionReason ?? null;
  const sendDisabledReason =
    "Прямая отправка через Desktop пока отключена: current full-access слой остаётся read-only. Черновик и локальная отметка работают честно.";

  if (loading && !reply) {
    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-4">
          <div className="text-base font-semibold text-white">Astra Assistant</div>
        </div>
        <div className="flex flex-1 flex-col gap-4 px-4 py-4">
          <ReplyPanelSkeleton />
        </div>
      </div>
    );
  }

  if (errorMessage) {
    return (
      <WarningState
        title="Assistant panel не загрузилась"
        description={errorMessage}
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

  if (!reply) {
    return (
      <EmptyState
        title="Assistant panel готова"
        description="Выбери чат и Astra покажет фокус, причины выбора, варианты ответа и рабочие действия."
      />
    );
  }

  if (!safeReply) {
    return (
      <WarningState
        title="Reply вернулся в неожиданном формате"
        description="Bridge отдал payload, который desktop не может безопасно отрисовать. Обнови экран или перезапусти локальный bridge."
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

  if (!suggestion) {
    return (
      <WarningState
        title="Reply пока не собран"
        description={safeReply.errorMessage || "Astra не смогла предложить ответ для выбранного контекста."}
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

  const triggerPreview = buildTriggerPreview(
    safeReply.sourceSenderName,
    safeReply.sourceMessagePreview || suggestion.sourceMessagePreview,
  );
  const currentDraftScopeKey = buildReplyDraftScopeKey({
    sourceMessageId: suggestion.sourceMessageId,
    focusLabel: suggestion.focusLabel,
    sourceMessagePreview: safeReply.sourceMessagePreview || suggestion.sourceMessagePreview,
    replyOpportunityMode: suggestion.replyOpportunityMode,
  });
  const draftScopeMatches = Boolean(
    workflowState?.draftText
      && workflowState.draftScopeKey
      && currentDraftScopeKey
      && workflowState.draftScopeKey === currentDraftScopeKey,
  );
  const legacyDraftMatches = Boolean(
    workflowState?.draftText
      && !workflowState.draftScopeKey
      && workflowState.draftSourceMessageId !== null
      && workflowState.draftSourceMessageId === suggestion.sourceMessageId,
  );
  const hasActiveDraft = Boolean(workflowState?.draftText && (draftScopeMatches || legacyDraftMatches));
  const hasStaleDraft = Boolean(workflowState?.draftText && !hasActiveDraft);

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
      <div className="border-b border-white/7 px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Assistant</div>
            <div className="text-base font-semibold text-white">Astra Reply</div>
            <div className="mt-1 text-sm leading-6 text-slate-400">
              Фокус строится по незакрытому триггеру из свежего окна сообщений.
            </div>
          </div>

          <Button
            variant="outline"
            size="icon-sm"
            className="border-white/8 bg-black/18 text-slate-100"
            onClick={onRefresh}
            disabled={refreshing}
          >
            {refreshing ? <LoaderCircle className="animate-spin" /> : <RefreshCcw />}
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/10">
            уверенность {formatConfidence(suggestion.confidence)}
          </Badge>
          <Badge variant="outline" className="border-0 bg-amber-300/10 text-amber-100 ring-1 ring-amber-300/10">
            риск {suggestion.riskLabel || "под контролем"}
          </Badge>
          <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
            style {suggestion.styleSource || "default"}
          </Badge>
          <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
            persona {suggestion.personaApplied ? "on" : "off"}
          </Badge>
          <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
            few-shot {suggestion.fewShotFound ? suggestion.fewShotMatchCount : 0}
          </Badge>
          <Badge
            variant="outline"
            className={cn(
              "border-0 ring-1",
              suggestion.llmStatus?.mode === "llm_refine"
                ? "bg-emerald-300/12 text-emerald-100 ring-emerald-300/15"
                : suggestion.llmStatus?.mode === "rejected_by_guardrails"
                  ? "bg-rose-400/12 text-rose-100 ring-rose-300/15"
                : suggestion.llmStatus?.mode === "fallback"
                  ? "bg-amber-300/12 text-amber-100 ring-amber-300/15"
                  : "bg-white/7 text-slate-200 ring-white/10",
            )}
          >
            LLM {suggestion.llmStatus?.label || "Deterministic"}
          </Badge>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-4 px-4 py-4">
          {freshness ? (
            <div
              className={cn(
                "rounded-[22px] border p-4",
                freshness.isStale
                  ? "border-amber-300/16 bg-amber-300/8"
                  : "border-emerald-300/14 bg-emerald-300/8",
              )}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-white">
                <DatabaseZap />
                {freshness.label}
              </div>
              <div className="text-sm leading-6 text-slate-200">{freshness.detail}</div>
              <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-300">
                {freshness.lastSyncAt ? <span>sync {formatDateTime(freshness.lastSyncAt)}</span> : null}
                {freshness.reference ? <span>{freshness.reference}</span> : null}
                {freshness.syncTrigger ? <span>{freshness.syncTrigger === "auto" ? "auto-sync" : "manual sync"}</span> : null}
                {freshness.updatedNow ? <span>хвост обновлён сейчас</span> : null}
                {freshness.canManualSync ? (
                  <span>
                    +{freshness.createdCount} новых • {freshness.updatedCount} обновлено
                  </span>
                ) : null}
                {freshness.syncError ? <span className="text-rose-100">{freshness.syncError}</span> : null}
              </div>
            </div>
          ) : null}

          <div className="rounded-[22px] border border-cyan-300/10 bg-cyan-400/8 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-cyan-100">
              <Sparkles />
              Фокус ответа
            </div>
            <div className="text-xl font-semibold tracking-tight text-white">
              {suggestion.focusLabel || "Нормальный рабочий ответ"}
            </div>
            <div className="mt-2 text-sm leading-6 text-cyan-50/85">
              {suggestion.focusReason || suggestion.reasonShort}
            </div>
            {suggestion.replyOpportunityMode === "follow_up_after_self" ? (
              <div className="mt-3 rounded-[18px] border border-cyan-300/12 bg-black/16 px-4 py-3 text-sm leading-6 text-cyan-50/90">
                <div className="text-[11px] uppercase tracking-[0.24em] text-cyan-200/70">
                  Почему reply уместен после твоего сообщения
                </div>
                <div className="mt-2">{suggestion.replyOpportunityReason || "В контексте остался незакрытый хвост."}</div>
              </div>
            ) : null}
            {triggerPreview ? (
              <div className="mt-3 rounded-[18px] border border-white/8 bg-black/16 px-4 py-3 text-sm leading-6 text-slate-200">
                <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Опорный триггер</div>
                <div className="mt-2">{triggerPreview}</div>
              </div>
            ) : null}
          </div>

          <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="text-sm font-medium text-white">Варианты ответа</div>
              <div className="text-xs text-slate-500">
                {replyOptions.length} варианта • обновлено {formatDateTime(new Date().toISOString())}
              </div>
            </div>
            <div className="flex flex-col gap-3">
              {replyOptions.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  className={cn(
                    "rounded-[20px] border px-4 py-4 text-left transition-all active:translate-y-px hover:border-cyan-300/12 hover:bg-cyan-400/6",
                    selectedIndex === index
                      ? "border-cyan-300/16 bg-cyan-400/8"
                      : "border-white/6 bg-white/[0.03]",
                  )}
                  onClick={() => setSelectedIndex(index)}
                >
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-white">{item.label}</div>
                    {selectedIndex === index ? (
                      <Badge variant="outline" className="border-0 bg-cyan-400/12 text-cyan-100 ring-1 ring-cyan-300/15">
                        выбран
                      </Badge>
                    ) : null}
                  </div>
                  {item.description ? (
                    <div className="mb-2 text-xs leading-5 text-slate-400">{item.description}</div>
                  ) : null}
                  <div className="whitespace-pre-wrap text-sm leading-6 text-slate-100">{item.text}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Button
              variant="outline"
              className="border-white/8 bg-black/16 text-slate-100"
              onClick={() => onCopy(selectedReply)}
              disabled={!selectedReply}
            >
              <Copy data-icon="inline-start" />
              Скопировать
            </Button>
            <Button
              className="bg-cyan-300 text-[#05111c] hover:bg-cyan-200"
              onClick={() => onUseDraft(selectedReply, suggestion.sourceMessageId)}
              disabled={!selectedReply}
            >
              <WandSparkles data-icon="inline-start" />
              Использовать как черновик
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="w-full">
                  <Button
                    variant="outline"
                    className="w-full border-white/8 bg-black/16 text-slate-300"
                    disabled
                  >
                    <Send data-icon="inline-start" />
                    Отправить через Desktop
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>{sendDisabledReason}</TooltipContent>
            </Tooltip>
            <Button
              variant="outline"
              className="border-white/8 bg-black/16 text-slate-100"
              onClick={() => onMarkSent(suggestion.sourceMessageId)}
            >
              <CheckCheck data-icon="inline-start" />
              Отметить отправленным
            </Button>
          </div>

          <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
              <ShieldAlert />
              Черновик и статус
            </div>

            {hasActiveDraft ? (
              <div className="rounded-[18px] border border-amber-300/12 bg-amber-300/8 px-4 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium text-amber-50">Локальный черновик сохранён</div>
                  <div className="text-xs text-amber-100/70">
                    {workflowState?.draftUpdatedAt ? formatDateTime(workflowState.draftUpdatedAt) : "сейчас"}
                  </div>
                </div>
                <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-100">
                  {workflowState?.draftText}
                </div>
                <div className="mt-3 flex gap-2">
                  <Button
                    variant="outline"
                    className="border-white/8 bg-black/18 text-slate-100"
                    onClick={() => onCopy(workflowState?.draftText || "")}
                  >
                    <Copy data-icon="inline-start" />
                    Скопировать черновик
                  </Button>
                  <Button
                    variant="outline"
                    className="border-white/8 bg-black/18 text-slate-100"
                    onClick={onClearDraft}
                  >
                    Очистить
                  </Button>
                </div>
              </div>
            ) : hasStaleDraft ? (
              <div className="rounded-[18px] border border-amber-300/12 bg-amber-300/8 px-4 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium text-amber-50">Черновик устарел для текущего фокуса</div>
                  <div className="text-xs text-amber-100/70">
                    {workflowState?.draftUpdatedAt ? formatDateTime(workflowState.draftUpdatedAt) : "сейчас"}
                  </div>
                </div>
                <div className="mt-2 text-sm leading-6 text-slate-100">
                  Текущий reply уже опирается на другой триггер или другой фокус, поэтому старый текст скрыт и не
                  показывается как актуальный.
                </div>
                <div className="mt-3 flex gap-2">
                  <Button
                    variant="outline"
                    className="border-white/8 bg-black/18 text-slate-100"
                    onClick={() => onCopy(workflowState?.draftText || "")}
                  >
                    <Copy data-icon="inline-start" />
                    Скопировать старый черновик
                  </Button>
                  <Button
                    variant="outline"
                    className="border-white/8 bg-black/18 text-slate-100"
                    onClick={onClearDraft}
                  >
                    Очистить
                  </Button>
                </div>
              </div>
            ) : (
              <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-300">
                Нажми «Использовать как черновик», чтобы зафиксировать текущий вариант локально и не потерять его при обновлении suggestion.
              </div>
            )}

            {workflowState?.sentAt ? (
              <div className="mt-3 rounded-[18px] border border-emerald-300/12 bg-emerald-300/8 px-4 py-3 text-sm leading-6 text-emerald-50">
                Последняя локальная отметка «отправлено»: {formatDateTime(workflowState.sentAt)}.
              </div>
            ) : null}
          </div>

          <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
            <div className="mb-3 text-sm font-medium text-white">Почему именно такой фокус</div>
            <div className="text-sm leading-6 text-slate-300">
              {suggestion.reasonShort || suggestion.focusReason}
            </div>

            <Separator className="my-4 bg-white/8" />

            <div className="flex flex-col gap-3 text-sm leading-6 text-slate-300">
              <div>Стратегия: {suggestion.strategy || "deterministic"}</div>
              {selectedVariant ? <div>Выбранный вариант: {selectedVariant.label}</div> : null}
              <div>Контекст: {suggestion.replyOpportunityReason || "стандартный reply"}</div>
              <div>Style profile: {suggestion.styleProfileKey || "без профиля"}</div>
              <div>Persona: {suggestion.personaApplied ? "применена" : "не применялась"}</div>
              <div>
                Few-shot: {suggestion.fewShotFound ? `найдено ${suggestion.fewShotMatchCount}` : "не использовались"}
              </div>
              <div>
                LLM: {suggestion.llmStatus?.label || "Deterministic"}
                {suggestion.llmStatus?.provider ? ` • ${suggestion.llmStatus.provider}` : ""}
              </div>
              {suggestion.llmStatus?.detail ? <div>LLM detail: {suggestion.llmStatus.detail}</div> : null}
              {suggestion.styleNotes.length > 0 ? (
                <div>Style notes: {suggestion.styleNotes.join(" • ")}</div>
              ) : null}
              {suggestion.personaNotes.length > 0 ? (
                <div>Persona notes: {suggestion.personaNotes.join(" • ")}</div>
              ) : null}
              {suggestion.fewShotNotes.length > 0 ? (
                <div>Few-shot notes: {suggestion.fewShotNotes.join(" • ")}</div>
              ) : null}
              {suggestion.guardrailFlags.length > 0 ? (
                <div>Guardrails: {suggestion.guardrailFlags.join(" • ")}</div>
              ) : null}
              {suggestion.llmRefineNotes.length > 0 ? (
                <div>LLM notes: {suggestion.llmRefineNotes.map(stringifyUnknown).join(" • ")}</div>
              ) : null}
            </div>

            <div className="mt-4 rounded-[18px] border border-white/6 bg-white/[0.03]">
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                onClick={() => setShowDebug((current) => !current)}
              >
                <div className="flex items-center gap-2 text-sm font-medium text-white">
                  <Bug className="size-4" />
                  Debug / details
                </div>
                <div className="inline-flex items-center gap-2 text-xs text-slate-400">
                  {suggestion.llmStatus?.label || "Deterministic"}
                  {showDebug ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
                </div>
              </button>

              {showDebug ? (
                <div className="border-t border-white/6 px-4 py-4 text-sm leading-6 text-slate-300">
                  <div>Режим: {suggestion.llmStatus?.mode || "deterministic"}</div>
                  <div className="mt-2">
                    Причина:{" "}
                    {llmDecisionReason?.detail
                      || suggestion.llmStatus?.detail
                      || "LLM refine не запрашивался, используется deterministic baseline."}
                  </div>
                  {llmDecisionReason?.flags.length ? (
                    <div className="mt-2">
                      Guardrails: {llmDecisionReason.flags.join(" • ")}
                    </div>
                  ) : null}
                  <div className="mt-4 text-[11px] uppercase tracking-[0.24em] text-slate-500">Baseline</div>
                  <div className="mt-2 whitespace-pre-wrap rounded-[14px] border border-white/6 bg-black/18 px-3 py-3 text-slate-100">
                    {llmDebug?.baselineText || suggestion.replyText || "Нет baseline."}
                  </div>
                  <div className="mt-4 text-[11px] uppercase tracking-[0.24em] text-slate-500">Raw LLM candidate</div>
                  <div className="mt-2 whitespace-pre-wrap rounded-[14px] border border-white/6 bg-black/18 px-3 py-3 text-slate-100">
                    {llmDebug?.rawCandidate || "Кандидат не сохранялся: LLM refine не применялся или провайдер не вернул текст."}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-[22px] border border-white/8 bg-black/16 px-4 py-4 text-sm leading-6 text-slate-300">
            <div className="mb-2 flex items-center gap-2 font-medium text-white">
              <ShieldAlert />
              Auto-send / autopilot
            </div>
            Beta-режим пока намеренно отключён. Основа под него есть: фокус, стиль, persona, few-shot и локальный draft state уже показываются прямо в рабочем контуре.
          </div>
        </div>
      </ScrollArea>
    </section>
  );
}

function buildTriggerPreview(senderName: string | null, preview: string | null): string | null {
  const safePreview = compactWhitespace(preview);
  const safeSender = compactWhitespace(senderName);
  if (!safePreview && !safeSender) {
    return null;
  }
  if (!safeSender) {
    return safePreview;
  }

  const cleanedPreview = stripSenderPrefix(safePreview || "", safeSender);
  return cleanedPreview ? `${safeSender}: ${cleanedPreview}` : safeSender;
}

function stripSenderPrefix(preview: string, senderName: string): string {
  let cleaned = compactWhitespace(preview) || "";
  const safeSender = compactWhitespace(senderName) || "";
  if (!cleaned || !safeSender) {
    return cleaned;
  }

  const prefixes = [`${safeSender}:`, `${safeSender} -`, `${safeSender} —`, `${safeSender} –`];
  while (cleaned) {
    const lowered = cleaned.toLocaleLowerCase();
    const matchedPrefix = prefixes.find((prefix) => lowered.startsWith(prefix.toLocaleLowerCase()));
    if (!matchedPrefix) {
      break;
    }
    cleaned = cleaned.slice(matchedPrefix.length).trimStart().replace(/^[:—–-]\s*/, "");
  }
  return cleaned;
}

function compactWhitespace(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const cleaned = value.replace(/\s+/g, " ").trim();
  return cleaned || null;
}

function ReplyPanelSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-32 rounded-[22px] bg-white/10" />
      <Skeleton className="h-44 rounded-[22px] bg-white/10" />
      <div className="grid grid-cols-2 gap-2">
        <Skeleton className="h-10 rounded-xl bg-white/10" />
        <Skeleton className="h-10 rounded-xl bg-white/10" />
        <Skeleton className="h-10 rounded-xl bg-white/10" />
        <Skeleton className="h-10 rounded-xl bg-white/10" />
      </div>
      <Skeleton className="h-40 rounded-[22px] bg-white/10" />
    </div>
  );
}
