import { useEffect, useMemo, useState } from "react";
import {
  Bug,
  ChevronDown,
  ChevronUp,
  CheckCheck,
  Copy,
  DatabaseZap,
  LoaderCircle,
  Power,
  RefreshCcw,
  Send,
  ShieldAlert,
  Sparkles,
  StopCircle,
  WandSparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatConfidence, formatDateTime, stringifyUnknown } from "@/lib/format";
import { normalizeAutopilotPayload, normalizeReplyPreviewPayload } from "@/lib/runtime-guards";
import type {
  AutopilotPayload,
  ChatFreshnessPayload,
  ReplyContextPayload,
  ReplyPreviewPayload,
  ReplyRetrievalPayload,
  ReplyStylePayload,
  WorkspaceStatusPayload,
} from "@/lib/types";
import { buildReplyDraftScopeKey, type ChatWorkspaceState } from "@/stores/app-store";
import { cn } from "@/lib/utils";

import { EmptyState } from "./EmptyState";
import { WarningState } from "./WarningState";

interface ReplyPanelProps {
  reply: ReplyPreviewPayload | null;
  replyContext?: ReplyContextPayload | null;
  autopilot?: AutopilotPayload | null;
  freshness?: ChatFreshnessPayload | null;
  workspaceStatus?: WorkspaceStatusPayload | null;
  workflowState: ChatWorkspaceState | null;
  loading?: boolean;
  refreshing?: boolean;
  sending?: boolean;
  sendStatus?: {
    status: string;
    message: string;
    backend: string | null;
    sentMessageKey: string | null;
    timestamp: string;
    tone: "success" | "error" | "pending" | "warning";
  } | null;
  autopilotUpdating?: boolean;
  errorMessage?: string | null;
  onRefresh: () => void;
  onCopy: (text: string) => void;
  onUseDraft: (text: string, sourceMessageId: number | null, sourceMessageKey: string | null) => void;
  onSend?: (
    text: string,
    sourceMessageId: number | null,
    sourceMessageKey: string | null,
    draftScopeKey: string | null,
  ) => void;
  onMarkSent: (sourceMessageId: number | null, sourceMessageKey: string | null) => void;
  onClearDraft: () => void;
  onUpdateAutopilotGlobal?: (payload: {
    mode?: string;
    master_enabled?: boolean;
    emergency_stop?: boolean;
    autopilot_paused?: boolean;
  }) => void;
  onUpdateChatAutopilot?: (payload: { trusted?: boolean; allowed?: boolean; autopilot_allowed?: boolean; mode?: string }) => void;
  onConfirmAutopilot?: (pendingId: string | null) => void;
  onEmergencyStop?: () => void;
}

export function ReplyPanel({
  reply,
  replyContext = null,
  autopilot = null,
  freshness = null,
  workspaceStatus = null,
  workflowState,
  loading = false,
  refreshing = false,
  sending = false,
  sendStatus = null,
  autopilotUpdating = false,
  errorMessage = null,
  onRefresh,
  onCopy,
  onUseDraft,
  onSend = () => undefined,
  onMarkSent,
  onClearDraft,
  onUpdateAutopilotGlobal = () => undefined,
  onUpdateChatAutopilot = () => undefined,
  onConfirmAutopilot = () => undefined,
  onEmergencyStop = () => undefined,
}: ReplyPanelProps) {
  const safeReply = normalizeReplyPreviewPayload(reply);
  const safeAutopilot = normalizeAutopilotPayload(autopilot);
  const suggestion = safeReply?.suggestion;
  const triggerDetails = suggestion?.trigger ?? null;
  const focusDetails = suggestion?.focus ?? null;
  const opportunityDetails = suggestion?.opportunity ?? null;
  const retrievalDetails = suggestion?.retrieval ?? null;
  const styleDetails = suggestion?.style ?? null;
  const fallbackDetails = suggestion?.fallback ?? null;
  const contextFocusLabel =
    replyContext?.focusLabel
    || focusDetails?.label
    || suggestion?.focusLabel
    || null;
  const contextFocusReason =
    replyContext?.focusReason
    || focusDetails?.reason
    || suggestion?.focusReason
    || null;
  const contextSourceMessageId =
    replyContext?.sourceLocalMessageId
    ?? suggestion?.sourceLocalMessageId
    ?? suggestion?.sourceMessageId
    ?? null;
  const contextSourceMessageKey =
    replyContext?.sourceMessageKey
    || suggestion?.sourceMessageKey
    || triggerDetails?.messageKey
    || null;
  const contextSourceMessagePreview =
    replyContext?.sourceMessagePreview
    || triggerDetails?.preview
    || suggestion?.sourceMessagePreview
    || safeReply?.sourceMessagePreview
    || null;
  const contextSourceSenderName =
    replyContext?.sourceSenderName
    || triggerDetails?.senderName
    || safeReply?.sourceSenderName
    || null;
  const contextReplyOpportunityMode =
    replyContext?.replyOpportunityMode
    || opportunityDetails?.mode
    || suggestion?.replyOpportunityMode
    || null;
  const contextReplyOpportunityReason =
    replyContext?.replyOpportunityReason
    || opportunityDetails?.reason
    || suggestion?.replyOpportunityReason
    || null;
  const replyRecommended = suggestion
    ? (opportunityDetails?.replyRecommended ?? suggestion.replyRecommended)
    : false;
  const isNoReply = Boolean(
    suggestion
      && (!replyRecommended || suggestion.strategy === "не отвечать"),
  );
  const replyOptions = useMemo(() => {
    if (!suggestion || isNoReply) {
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
  }, [isNoReply, suggestion]);

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showDebug, setShowDebug] = useState(false);
  const [draftText, setDraftText] = useState("");
  const triggerPreview = buildTriggerPreview(
    contextSourceSenderName,
    contextSourceMessagePreview,
  );

  useEffect(() => {
    setSelectedIndex(0);
    setShowDebug(false);
  }, [contextSourceMessageId, contextSourceMessagePreview, suggestion?.replyText]);

  const selectedReply = replyOptions[selectedIndex]?.text || "";
  const selectedVariant = replyOptions[selectedIndex] || null;
  const llmDebug = suggestion?.llmDebug ?? null;
  const llmDecisionReason = llmDebug?.decisionReason ?? null;
  const llmStatusLabel = suggestion?.llmStatus?.label || "Детерминированный";
  const triggerBackendLabel = compactWhitespace(triggerDetails?.backend || suggestion?.sourceBackend || null);
  const retrievalSummary = buildRetrievalSummary(retrievalDetails);
  const styleSummary = buildStyleSummary(styleDetails, suggestion);
  const currentDraftScopeKey =
    replyContext?.draftScopeKey
    || buildReplyDraftScopeKey({
      sourceMessageId: contextSourceMessageId,
      sourceMessageKey: contextSourceMessageKey,
      focusLabel: contextFocusLabel,
      sourceMessagePreview: contextSourceMessagePreview,
      replyOpportunityMode: contextReplyOpportunityMode,
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
      && workflowState.draftSourceMessageId === contextSourceMessageId,
  );
  const hasActiveDraft = Boolean(workflowState?.draftText && (draftScopeMatches || legacyDraftMatches));
  const hasStaleDraft = Boolean(workflowState?.draftText && !hasActiveDraft);
  const autopilotPending = safeAutopilot?.pendingDraft ?? null;
  const autopilotPendingId = autopilotPending?.executionId || autopilotPending?.id || null;
  const autopilotMode = safeAutopilot?.mode || "off";
  const autopilotEffectiveMode = safeAutopilot?.effectiveMode || autopilotMode;
  const autopilotAllowed = Boolean(safeAutopilot?.autopilotAllowed ?? safeAutopilot?.allowed);
  const autopilotBlockedReason = safeAutopilot?.decision.reason || safeAutopilot?.state?.reason || null;
  const autopilotReasonCode = safeAutopilot?.decision.reasonCode || safeAutopilot?.state?.reasonCode || null;
  useEffect(() => {
    const activeDraft = hasActiveDraft ? workflowState?.draftText || "" : "";
    setDraftText(activeDraft || selectedReply || "");
  }, [hasActiveDraft, selectedReply, workflowState?.draftScopeKey, workflowState?.draftText]);

  const sendDisabledReason =
    safeReply?.actions.disabledReason
    || workspaceStatus?.sendDisabledReason
    || (workspaceStatus?.availability.sendAvailable ? null : "Write-path на этом этапе выключен.")
    || "Отправка сейчас недоступна.";
  const sendAllowed = Boolean(
    safeReply?.actions.send
      && (workspaceStatus?.availability.sendAvailable ?? true)
      && !isNoReply,
  );
  const hasContextOnlyWorkspace = Boolean(replyContext?.available && !suggestion);

  if (loading && !reply) {
    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-4">
          <div className="text-base font-semibold text-white">Панель Astra</div>
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
        title="Панель ответов не загрузилась"
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
        title="Панель ответов готова"
        description="Выбери чат и Astra покажет фокус, причины выбора, варианты ответа и рабочие действия."
      />
    );
  }

  if (!safeReply) {
    return (
      <WarningState
        title="Ответ вернулся в неожиданном формате"
        description="Bridge отдал данные, которые desktop не может безопасно отрисовать. Обнови экран или перезапусти локальный bridge."
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
    if (hasContextOnlyWorkspace) {
      return (
        <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
          <div className="border-b border-white/7 px-4 py-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Контекст</div>
                <div className="text-base font-semibold text-white">Astra Reply</div>
                <div className="mt-1 text-sm leading-6 text-slate-400">
                  Workspace уже собрал общий trigger и focus, но нормальный draft сейчас не получился.
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
          </div>

          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-4 px-4 py-4">
              {workspaceStatus ? (
                <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
                  <div className="mb-2 flex items-center gap-2 text-sm font-medium text-white">
                    <DatabaseZap />
                    Workspace status
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                      {workspaceStatus.source}
                    </Badge>
                    <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                      {workspaceStatus.messageSource.backend}
                    </Badge>
                    {!workspaceStatus.availability.sendAvailable ? (
                      <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15">
                        read-only
                      </Badge>
                    ) : null}
                    {workspaceStatus.degraded ? (
                      <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15">
                        degraded
                      </Badge>
                    ) : null}
                  </div>
                  <div className="mt-3 text-sm leading-6 text-slate-300">
                    {workspaceStatus.degradedReason
                      || sendDisabledReason
                      || "Этот snapshot сейчас используется только для чтения и focus context."}
                  </div>
                </div>
              ) : null}

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
                </div>
              ) : null}

              <div className="rounded-[22px] border border-cyan-300/10 bg-cyan-400/8 p-4">
                <div className="mb-2 flex items-center gap-2 text-sm font-medium text-cyan-100">
                  <Sparkles />
                  Фокус ответа
                </div>
                <div className="text-xl font-semibold tracking-tight text-white">
                  {contextFocusLabel || "Контекст доступен"}
                </div>
                <div className="mt-2 text-sm leading-6 text-cyan-50/85">
                  {contextFocusReason || contextReplyOpportunityReason || "Workspace snapshot уже собрал опорный trigger."}
                </div>
                {triggerPreview ? (
                  <div className="mt-3 rounded-[18px] border border-white/8 bg-black/16 px-4 py-3 text-sm leading-6 text-slate-200">
                    <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Опорный триггер</div>
                    <div className="mt-2">{triggerPreview}</div>
                  </div>
                ) : null}
              </div>

              <div className="rounded-[22px] border border-white/8 bg-black/16 p-4 text-sm leading-6 text-slate-300">
                Message list и reply panel всё равно смотрят в один и тот же snapshot. Если draft не собрался,
                здесь остаётся честный focus context без декоративного фейка.
              </div>
            </div>
          </ScrollArea>
        </section>
      );
    }

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

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/7 bg-white/[0.035]">
      <div className="border-b border-white/7 px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Ответы</div>
            <div className="text-base font-semibold text-white">Astra Reply</div>
            <div className="mt-1 text-sm leading-6 text-slate-400">
              Фокус и варианты строятся из того же workspace snapshot, что и message list.
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
          <Badge
            variant="outline"
            className={cn(
              "border-0 ring-1",
              isNoReply
                ? "bg-amber-300/12 text-amber-50 ring-amber-300/15"
                : "bg-amber-300/10 text-amber-100 ring-amber-300/10",
            )}
          >
            {isNoReply ? "лучше не отвечать" : `риск ${suggestion.riskLabel || "под контролем"}`}
          </Badge>
          <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
            стиль {styleDetails?.source || suggestion.styleSource || "по умолчанию"}
          </Badge>
          <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
            retrieval {retrievalDetails?.used ? retrievalDetails.matchCount : 0}
          </Badge>
          <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
            {triggerBackendLabel || "backend не указан"}
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
            LLM {llmStatusLabel}
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
                {freshness.lastSyncAt ? <span>синхронизация {formatDateTime(freshness.lastSyncAt)}</span> : null}
                {freshness.reference ? <span>{freshness.reference}</span> : null}
                {freshness.syncTrigger ? <span>{freshness.syncTrigger === "auto" ? "автосинхронизация" : "ручная синхронизация"}</span> : null}
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

          {workspaceStatus ? (
            <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-white">
                <DatabaseZap />
                Workspace status
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                  {workspaceStatus.source}
                </Badge>
                <Badge variant="outline" className="border-0 bg-white/7 text-slate-200 ring-1 ring-white/10">
                  {workspaceStatus.messageSource.backend}
                </Badge>
                {!workspaceStatus.availability.sendAvailable ? (
                  <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15">
                    read-only
                  </Badge>
                ) : null}
                {workspaceStatus.degraded ? (
                  <Badge variant="outline" className="border-0 bg-amber-300/12 text-amber-100 ring-1 ring-amber-300/15">
                    degraded
                  </Badge>
                ) : null}
              </div>
              {workspaceStatus.degradedReason || workspaceStatus.syncError ? (
                <div className="mt-3 text-sm leading-6 text-slate-300">
                  {workspaceStatus.degradedReason || workspaceStatus.syncError}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="rounded-[22px] border border-cyan-300/10 bg-cyan-400/8 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-cyan-100">
              <Sparkles />
              Фокус ответа
            </div>
            <div className="text-xl font-semibold tracking-tight text-white">
              {contextFocusLabel || "Нормальный рабочий ответ"}
            </div>
            <div className="mt-2 text-sm leading-6 text-cyan-50/85">
              {contextFocusReason || suggestion.reasonShort}
            </div>
            {contextReplyOpportunityMode === "follow_up_after_self" ? (
              <div className="mt-3 rounded-[18px] border border-cyan-300/12 bg-black/16 px-4 py-3 text-sm leading-6 text-cyan-50/90">
                <div className="text-[11px] uppercase tracking-[0.24em] text-cyan-200/70">
                  Почему reply уместен после твоего сообщения
                </div>
                <div className="mt-2">{contextReplyOpportunityReason || "В контексте остался незакрытый хвост."}</div>
              </div>
            ) : null}
            {triggerPreview ? (
              <div className="mt-3 rounded-[18px] border border-white/8 bg-black/16 px-4 py-3 text-sm leading-6 text-slate-200">
                <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Опорный триггер</div>
                <div className="mt-2">{triggerPreview}</div>
              </div>
            ) : null}
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-[20px] border border-white/8 bg-black/16 p-4">
              <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Trigger</div>
              <div className="mt-2 text-sm font-medium text-white">
                {contextReplyOpportunityMode === "follow_up_after_self" ? "follow-up после твоего сообщения" : "прямой повод"}
              </div>
              <div className="mt-2 text-sm leading-6 text-slate-300">
                {contextReplyOpportunityReason || "Свежий смысловой хвост без ответа."}
              </div>
            </div>

            <div className="rounded-[20px] border border-white/8 bg-black/16 p-4">
              <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Retrieval</div>
              <div className="mt-2 text-sm font-medium text-white">
                {retrievalDetails?.used ? `${retrievalDetails.matchCount} похожих ответа` : "Без похожих ответов"}
              </div>
              <div className="mt-2 text-sm leading-6 text-slate-300">
                {retrievalSummary}
              </div>
            </div>

            <div className="rounded-[20px] border border-white/8 bg-black/16 p-4">
              <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Style</div>
              <div className="mt-2 text-sm font-medium text-white">
                {styleDetails?.profileKey || suggestion.styleProfileKey || "Без профиля"}
              </div>
              <div className="mt-2 text-sm leading-6 text-slate-300">
                {styleSummary}
              </div>
            </div>
          </div>

          {isNoReply ? (
            <div className="rounded-[22px] border border-amber-300/16 bg-amber-300/8 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-amber-50">
                <ShieldAlert />
                Сейчас лучше не отвечать
              </div>
              <div className="text-sm leading-6 text-slate-100">
                {contextReplyOpportunityReason || suggestion.reasonShort || "Явного повода писать сейчас нет."}
              </div>
              {suggestion.alternativeAction ? (
                <div className="mt-3 rounded-[18px] border border-white/8 bg-black/18 px-4 py-3 text-sm leading-6 text-slate-200">
                  {suggestion.alternativeAction}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="text-sm font-medium text-white">Варианты ответа</div>
              <div className="text-xs text-slate-500">
                {replyOptions.length} варианта • обновлено {formatDateTime(new Date().toISOString())}
              </div>
            </div>
            <div className="mb-3 flex flex-wrap gap-2">
              {[
                ["short", "Короче"],
                ["soft", "Мягче"],
                ["style", "В моём стиле"],
              ].map(([variantId, label]) => {
                const index = replyOptions.findIndex((item) => item.id === variantId);
                return (
                  <Button
                    key={variantId}
                    type="button"
                    variant="outline"
                    size="sm"
                    className="border-white/8 bg-black/16 text-slate-100"
                    disabled={index < 0}
                    onClick={() => setSelectedIndex(index)}
                  >
                    {label}
                  </Button>
                );
              })}
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="border-white/8 bg-black/16 text-slate-100"
                onClick={onRefresh}
                disabled={refreshing}
              >
                Пересобрать
              </Button>
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
                    <div className="flex items-center gap-2">
                      {item.id === "primary" ? (
                        <Badge variant="outline" className="border-0 bg-white/8 text-white ring-1 ring-white/10">
                          основной
                        </Badge>
                      ) : null}
                      {selectedIndex === index ? (
                        <Badge variant="outline" className="border-0 bg-cyan-400/12 text-cyan-100 ring-1 ring-cyan-300/15">
                          выбран
                        </Badge>
                      ) : null}
                    </div>
                  </div>
                  {item.description ? (
                    <div className="mb-2 text-xs leading-5 text-slate-400">{item.description}</div>
                  ) : null}
                  <div className="whitespace-pre-wrap text-sm leading-6 text-slate-100">{item.text}</div>
                </button>
              ))}
            </div>
            </div>
          )}

          {!isNoReply ? (
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
              onClick={() => {
                setDraftText(selectedReply);
                onUseDraft(selectedReply, contextSourceMessageId, contextSourceMessageKey);
              }}
              disabled={!selectedReply}
              aria-label="Использовать как черновик"
            >
              <WandSparkles data-icon="inline-start" />
              Вставить в черновик
            </Button>
            <Button
              variant="outline"
              className="border-white/8 bg-black/16 text-slate-100"
              onClick={() => onMarkSent(contextSourceMessageId, contextSourceMessageKey)}
            >
              <CheckCheck data-icon="inline-start" />
              Отметить отправленным
            </Button>
            </div>
          ) : null}

          {!isNoReply ? (
            <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
              <ShieldAlert />
              Черновик перед отправкой
            </div>

            <textarea
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              rows={5}
              className="min-h-28 w-full resize-y rounded-[18px] border border-white/8 bg-black/24 px-4 py-3 text-sm leading-6 text-slate-100 outline-none transition focus:border-cyan-300/24 focus:bg-black/32"
              placeholder="Вставь вариант, поправь формулировку и отправь явно."
            />
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Button
                variant="outline"
                className="border-white/8 bg-black/18 text-slate-100"
                onClick={() => onUseDraft(draftText, contextSourceMessageId, contextSourceMessageKey)}
                disabled={!draftText.trim()}
              >
                Сохранить черновик
              </Button>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="w-full">
                    <Button
                      className="w-full bg-emerald-300 text-[#05111c] hover:bg-emerald-200"
                      onClick={() => onSend(draftText, contextSourceMessageId, contextSourceMessageKey, currentDraftScopeKey)}
                      disabled={!sendAllowed || !draftText.trim() || sending}
                    >
                      {sending ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Send data-icon="inline-start" />}
                      Отправить
                    </Button>
                  </span>
                </TooltipTrigger>
                {!sendAllowed ? <TooltipContent>{sendDisabledReason}</TooltipContent> : null}
              </Tooltip>
            </div>

            {sendStatus ? (
              <div
                className={cn(
                  "mt-3 rounded-[18px] border px-4 py-3 text-sm leading-6",
                  sendStatus.tone === "success"
                    ? "border-emerald-300/12 bg-emerald-300/8 text-emerald-50"
                    : sendStatus.tone === "pending"
                      ? "border-cyan-300/12 bg-cyan-300/8 text-cyan-50"
                    : sendStatus.tone === "warning"
                      ? "border-amber-300/12 bg-amber-300/8 text-amber-50"
                      : "border-rose-300/12 bg-rose-400/8 text-rose-50",
                )}
              >
                <div className="font-medium">{sendStatus.message}</div>
                <div className="mt-1 text-xs opacity-80">
                  {sendStatus.backend ? `backend ${sendStatus.backend}` : "backend не выбран"}
                  {sendStatus.sentMessageKey ? ` • ${sendStatus.sentMessageKey}` : ""}
                  {" • "}
                  {formatDateTime(sendStatus.timestamp)}
                </div>
              </div>
            ) : null}

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
                Нажми «Использовать как черновик», чтобы зафиксировать текущий вариант локально и не потерять его при обновлении предложения.
              </div>
            )}

            {workflowState?.sentAt ? (
              <div className="mt-3 rounded-[18px] border border-emerald-300/12 bg-emerald-300/8 px-4 py-3 text-sm leading-6 text-emerald-50">
                Последняя локальная отметка «отправлено»: {formatDateTime(workflowState.sentAt)}.
              </div>
            ) : null}
            </div>
          ) : null}

          <div className="rounded-[22px] border border-white/8 bg-black/16 p-4">
            <div className="mb-3 text-sm font-medium text-white">Почему именно такой фокус</div>
            <div className="text-sm leading-6 text-slate-300">
              {suggestion.reasonShort || focusDetails?.reason || suggestion.focusReason}
            </div>

            <Separator className="my-4 bg-white/8" />

            <div className="flex flex-col gap-3 text-sm leading-6 text-slate-300">
              <div>Стратегия: {suggestion.strategy || "детерминированная база"}</div>
              {selectedVariant ? <div>Выбранный вариант: {selectedVariant.label}</div> : null}
              <div>Триггер: {triggerPreview || "нет явного trigger preview"}</div>
              <div>Контекст: {contextReplyOpportunityReason || "стандартный ответ"}</div>
              <div>Фокус score: {formatConfidence(focusDetails?.score ?? suggestion.focusScore)}</div>
              <div>Окно выбора: {focusDetails?.selectionMessageCount || suggestion.selectionMessageCount || 0} сообщений</div>
              <div>Профиль стиля: {styleDetails?.profileKey || suggestion.styleProfileKey || "без профиля"}</div>
              <div>Персона: {styleDetails?.personaApplied ?? suggestion.personaApplied ? "применена" : "не применялась"}</div>
              <div>Похожие ответы: {retrievalDetails?.used ? `найдено ${retrievalDetails.matchCount}` : "не использовались"}</div>
              <div>
                LLM: {llmStatusLabel}
                {suggestion.llmStatus?.provider ? ` • ${suggestion.llmStatus.provider}` : ""}
              </div>
              {suggestion.llmStatus?.detail ? <div>Деталь LLM: {suggestion.llmStatus.detail}</div> : null}
              {styleDetails?.sourceReason ? <div>Источник стиля: {styleDetails.sourceReason}</div> : null}
              {styleDetails?.notes.length ? (
                <div>Заметки стиля: {styleDetails.notes.join(" • ")}</div>
              ) : null}
              {styleDetails?.personaNotes.length ? (
                <div>Заметки персоны: {styleDetails.personaNotes.join(" • ")}</div>
              ) : null}
              {retrievalDetails?.notes.length ? (
                <div>Заметки похожих ответов: {retrievalDetails.notes.join(" • ")}</div>
              ) : null}
              {suggestion.guardrailFlags.length > 0 ? (
                <div>Ограничители: {suggestion.guardrailFlags.join(" • ")}</div>
              ) : null}
              {fallbackDetails?.reason ? <div>Fallback: {fallbackDetails.reason}</div> : null}
              {suggestion.llmRefineNotes.length > 0 ? (
                <div>Заметки LLM: {suggestion.llmRefineNotes.map(stringifyUnknown).join(" • ")}</div>
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
                  Отладка / детали
                </div>
                <div className="inline-flex items-center gap-2 text-xs text-slate-400">
                  {llmStatusLabel}
                  {showDebug ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
                </div>
              </button>

              {showDebug ? (
                <div className="border-t border-white/6 px-4 py-4 text-sm leading-6 text-slate-300">
                  <div>Режим: {suggestion.llmStatus?.mode || "детерминированный"}</div>
                  <div className="mt-2">Trigger backend: {triggerBackendLabel || "не указан"}</div>
                  <div className="mt-2">Trigger key: {triggerDetails?.messageKey || "нет"}</div>
                  <div className="mt-2">Focus: {contextFocusLabel || "нет"}</div>
                  <div className="mt-2">Opportunity: {contextReplyOpportunityMode || "hold"}</div>
                  <div className="mt-2">
                    Причина:{" "}
                    {llmDecisionReason?.detail
                      || suggestion.llmStatus?.detail
                      || "LLM-улучшение не запрашивалось, используется детерминированная база."}
                  </div>
                  {contextReplyOpportunityReason ? (
                    <div className="mt-2">Почему reply уместен: {contextReplyOpportunityReason}</div>
                  ) : null}
                  {retrievalDetails ? (
                    <div className="mt-2">
                      Retrieval: {retrievalSummary}
                    </div>
                  ) : null}
                  {styleSummary ? <div className="mt-2">Style: {styleSummary}</div> : null}
                  {fallbackDetails?.reason ? <div className="mt-2">Fallback: {fallbackDetails.reason}</div> : null}
                  {llmDecisionReason?.flags.length ? (
                    <div className="mt-2">
                      Ограничители: {llmDecisionReason.flags.join(" • ")}
                    </div>
                  ) : null}
                  {retrievalDetails?.hits.length ? (
                    <>
                      <div className="mt-4 text-[11px] uppercase tracking-[0.24em] text-slate-500">Похожие реальные ответы</div>
                      <div className="mt-2 flex flex-col gap-2">
                        {retrievalDetails.hits.slice(0, 3).map((item) => (
                          <div
                            key={`${item.id}-${item.score ?? "score"}`}
                            className="rounded-[14px] border border-white/6 bg-black/18 px-3 py-3"
                          >
                            <div className="text-xs text-slate-400">
                              {item.chatTitle}
                              {item.score !== null ? ` • score ${item.score.toFixed(2)}` : ""}
                            </div>
                            <div className="mt-1 text-slate-200">Входящее: {item.inboundText}</div>
                            <div className="mt-1 text-slate-100">Исходящее: {item.outboundText}</div>
                            {item.reasons.length ? (
                              <div className="mt-1 text-xs text-slate-400">{item.reasons.join(" • ")}</div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </>
                  ) : null}
                  <div className="mt-4 text-[11px] uppercase tracking-[0.24em] text-slate-500">Базовый вариант</div>
                  <div className="mt-2 whitespace-pre-wrap rounded-[14px] border border-white/6 bg-black/18 px-3 py-3 text-slate-100">
                    {llmDebug?.baselineText || suggestion.replyText || "Нет базового варианта."}
                  </div>
                  <div className="mt-4 text-[11px] uppercase tracking-[0.24em] text-slate-500">Сырой LLM-кандидат</div>
                  <div className="mt-2 whitespace-pre-wrap rounded-[14px] border border-white/6 bg-black/18 px-3 py-3 text-slate-100">
                    {llmDebug?.rawCandidate || "Кандидат не сохранялся: LLM-улучшение не применялось или провайдер не вернул текст."}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-[22px] border border-white/8 bg-black/16 px-4 py-4 text-sm leading-6 text-slate-300">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 font-medium text-white">
                <ShieldAlert />
                Autopilot
              </div>
              {safeAutopilot ? (
                <Badge
                  variant="outline"
                  className={cn(
                    "border-0 ring-1",
                    safeAutopilot.decision.allowed
                      ? "bg-emerald-300/12 text-emerald-100 ring-emerald-300/15"
                      : "bg-white/7 text-slate-200 ring-white/10",
                  )}
                >
                  {formatAutopilotMode(autopilotEffectiveMode)}
                </Badge>
              ) : null}
            </div>

            {safeAutopilot ? (
              <div className="flex flex-col gap-3">
                <div
                  className={cn(
                    "rounded-[18px] border px-4 py-3",
                    safeAutopilot.emergencyStop
                      ? "border-rose-300/16 bg-rose-400/8"
                      : safeAutopilot.masterEnabled
                        ? "border-emerald-300/14 bg-emerald-300/8"
                        : "border-white/6 bg-white/[0.03]",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Безопасность</div>
                      <div className="mt-1 font-medium text-white">
                        {safeAutopilot.emergencyStop
                          ? "Экстренный стоп активен"
                          : safeAutopilot.masterEnabled
                            ? `Глобально: ${formatAutopilotMode(safeAutopilot.globalMode)}`
                            : "Глобально выключено"}
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      className="border-rose-300/14 bg-rose-400/8 text-rose-50"
                      disabled={autopilotUpdating || safeAutopilot.emergencyStop}
                      onClick={onEmergencyStop}
                    >
                      <StopCircle data-icon="inline-start" />
                      Экстренный стоп
                    </Button>
                  </div>
                  {safeAutopilot.autopilotPaused ? (
                    <div className="mt-2 text-xs text-amber-100">Автопилот на паузе, автоотправка не выполняется.</div>
                  ) : null}
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <label className="flex flex-col gap-2">
                    <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Глобальный режим</span>
                    <select
                      value={safeAutopilot.globalMode || "off"}
                      disabled={autopilotUpdating || safeAutopilot.emergencyStop}
                      onChange={(event) => onUpdateAutopilotGlobal({ mode: event.target.value })}
                      className="rounded-[16px] border border-white/8 bg-black/24 px-3 py-2 text-sm text-slate-100 outline-none"
                    >
                      <option value="off">Выключен</option>
                      <option value="draft">Черновик</option>
                      <option value="semi_auto">Полуавтомат</option>
                      <option value="autopilot">Автопилот</option>
                    </select>
                  </label>

                  <label className="flex flex-col gap-2">
                    <span className="text-xs uppercase tracking-[0.22em] text-slate-500">Режим чата</span>
                    <select
                      value={autopilotMode === "confirm" ? "semi_auto" : autopilotMode}
                      disabled={autopilotUpdating}
                      onChange={(event) => onUpdateChatAutopilot({ mode: event.target.value })}
                      className="rounded-[16px] border border-white/8 bg-black/24 px-3 py-2 text-sm text-slate-100 outline-none"
                    >
                      <option value="off">Выключен</option>
                      <option value="draft">Черновик</option>
                      <option value="semi_auto">Полуавтомат</option>
                      <option value="autopilot">Автопилот</option>
                    </select>
                  </label>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="outline"
                    className={cn(
                      "border-white/8 bg-black/18 text-slate-100",
                      safeAutopilot.trusted ? "border-cyan-300/18 bg-cyan-300/10 text-cyan-50" : "",
                    )}
                    disabled={autopilotUpdating}
                    onClick={() => onUpdateChatAutopilot({ trusted: !safeAutopilot.trusted })}
                  >
                    {safeAutopilot.trusted ? "Доверенный чат" : "Не доверенный"}
                  </Button>
                  <Button
                    variant="outline"
                    className={cn(
                      "border-white/8 bg-black/18 text-slate-100",
                      autopilotAllowed ? "border-emerald-300/18 bg-emerald-300/10 text-emerald-50" : "",
                    )}
                    disabled={autopilotUpdating}
                    onClick={() => onUpdateChatAutopilot({ autopilot_allowed: !autopilotAllowed, allowed: !autopilotAllowed })}
                  >
                    {autopilotAllowed ? "Автопилот разрешён" : "Автопилот запрещён"}
                  </Button>
                </div>

                <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                  <div className="mb-1 text-xs uppercase tracking-[0.22em] text-slate-500">Решение сейчас</div>
                  <div className="text-slate-100">{autopilotBlockedReason || "Решения пока нет."}</div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-400">
                    <span>статус: {safeAutopilot.state?.status || safeAutopilot.decision.status || "idle"}</span>
                    <span>код: {autopilotReasonCode || "none"}</span>
                    <span>триггер: {safeAutopilot.decision.trigger || "нет"}</span>
                    <span>уверенность: {formatConfidence(safeAutopilot.decision.confidence)}</span>
                    {safeAutopilot.cooldown.active ? (
                      <span>пауза: {safeAutopilot.cooldown.remainingSeconds}с</span>
                    ) : null}
                    {safeAutopilot.writeReady ? <span>запись готова</span> : <span>запись закрыта</span>}
                  </div>
                </div>

                {autopilotPending?.text ? (
                  <div className="rounded-[18px] border border-amber-300/12 bg-amber-300/8 px-4 py-3">
                    <div className="mb-1 text-xs uppercase tracking-[0.22em] text-amber-100/70">
                      {autopilotPending.status === "awaiting_confirmation" ? "Ждёт подтверждения" : "Авточерновик"}
                    </div>
                    <div className="whitespace-pre-wrap text-slate-100">{autopilotPending.text}</div>
                    <div className="mt-3 flex gap-2">
                      <Button
                        variant="outline"
                        className="border-white/8 bg-black/18 text-slate-100"
                        onClick={() => {
                          const text = autopilotPending?.text || "";
                          setDraftText(text);
                          onUseDraft(
                            text,
                            safeAutopilot.decision.sourceMessageId,
                            safeAutopilot.decision.sourceMessageKey || contextSourceMessageKey,
                          );
                        }}
                      >
                        Вставить
                      </Button>
                      {autopilotPending.status === "awaiting_confirmation" ? (
                        <Button
                          className="bg-emerald-300 text-[#05111c] hover:bg-emerald-200"
                          disabled={autopilotUpdating || sending}
                          onClick={() => onConfirmAutopilot(autopilotPendingId)}
                        >
                          <Send data-icon="inline-start" />
                          Подтвердить отправку
                        </Button>
                      ) : (
                        <Button
                          className="bg-emerald-300 text-[#05111c] hover:bg-emerald-200"
                          disabled={!sendAllowed || sending}
                          onClick={() => onSend(
                            autopilotPending?.text || "",
                            safeAutopilot.decision.sourceMessageId,
                            safeAutopilot.decision.sourceMessageKey || contextSourceMessageKey,
                            safeAutopilot.decision.draftScopeKey || currentDraftScopeKey,
                          )}
                        >
                          Отправить вручную
                        </Button>
                      )}
                    </div>
                  </div>
                ) : null}

                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="outline"
                    className="border-white/8 bg-black/18 text-slate-100"
                    disabled={autopilotUpdating}
                    onClick={() => onUpdateAutopilotGlobal({ autopilot_paused: !safeAutopilot.autopilotPaused })}
                  >
                    <Power data-icon="inline-start" />
                    {safeAutopilot.autopilotPaused ? "Снять паузу" : "Пауза автопилота"}
                  </Button>
                  <Button
                    variant="outline"
                    className="border-rose-300/14 bg-rose-400/8 text-rose-50"
                    disabled={autopilotUpdating}
                    onClick={() => onUpdateChatAutopilot({ trusted: false, allowed: false, autopilot_allowed: false, mode: "off" })}
                  >
                    <StopCircle data-icon="inline-start" />
                    Стоп для чата
                  </Button>
                </div>

                {safeAutopilot.journal.length > 0 ? (
                  <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                    <div className="mb-2 text-xs uppercase tracking-[0.22em] text-slate-500">
                      Последние действия
                    </div>
                    <div className="flex flex-col gap-2">
                      {safeAutopilot.journal.slice(0, 3).map((item, index) => (
                        <div key={`${item.timestamp || "event"}-${index}`} className="text-xs leading-5 text-slate-300">
                          <span className="text-slate-100">{item.message || item.status || "событие"}</span>
                          {item.reason ? ` — ${item.reason}` : ""}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="rounded-[18px] border border-white/6 bg-white/[0.03] px-4 py-3">
                Состояние автопилота пока не пришло от bridge.
              </div>
            )}
          </div>
        </div>
      </ScrollArea>
    </section>
  );
}

function formatAutopilotMode(mode: string | null | undefined): string {
  if (mode === "draft") {
    return "Черновик";
  }
  if (mode === "confirm" || mode === "semi_auto") {
    return "Полуавтомат";
  }
  if (mode === "autopilot") {
    return "Автопилот";
  }
  return "Выключен";
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

function buildRetrievalSummary(
  retrieval: ReplyRetrievalPayload | null | undefined,
): string {
  if (!retrieval || !retrieval.used) {
    return "Few-shot слой не повлиял на generation.";
  }

  const parts = [
    retrieval.strategyBias ? `bias ${retrieval.strategyBias}` : null,
    retrieval.lengthHint ? `длина ${retrieval.lengthHint}` : null,
    retrieval.rhythmHint ? `ритм ${retrieval.rhythmHint}` : null,
    retrieval.dominantTopicHint ? `тема ${retrieval.dominantTopicHint}` : null,
    retrieval.notes[0] || null,
  ].filter((item): item is string => Boolean(item));

  return parts.join(" • ") || "Похожие реальные ответы повлияли на тон и ритм.";
}

function buildStyleSummary(
  style: ReplyStylePayload | null | undefined,
  suggestion: ReplyPreviewPayload["suggestion"] | null | undefined,
): string {
  if (!style && !suggestion) {
    return "Стиль не определён.";
  }

  const parts = [
    style?.sourceReason || suggestion?.styleSourceReason || null,
    style?.notes[0] || suggestion?.styleNotes[0] || null,
    (style?.personaApplied ?? suggestion?.personaApplied) ? "persona подмешана аккуратно" : null,
  ].filter((item): item is string => Boolean(item));

  return parts.join(" • ") || "Стиль держится ближе к твоей реальной переписке.";
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
