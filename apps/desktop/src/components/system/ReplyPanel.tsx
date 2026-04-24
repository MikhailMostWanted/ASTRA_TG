import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Bug,
  ChevronDown,
  ChevronUp,
  CheckCheck,
  Copy,
  FileText,
  LoaderCircle,
  Heart,
  MessageSquare,
  Minimize2,
  Pause,
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
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  buildAutopilotCopy,
  buildFreshnessCopy,
  buildLiveCopy,
  buildWorkspaceCopy,
  compactReason,
  formatAutopilotMode,
  toneBadgeClasses,
  tonePanelClasses,
  type UiStatusCopy,
  type UiTone,
} from "@/lib/chat-ux";
import { formatConfidence, formatDateTime } from "@/lib/format";
import { normalizeAutopilotPayload, normalizeReplyPreviewPayload } from "@/lib/runtime-guards";
import type {
  AutopilotPayload,
  ChatFreshnessPayload,
  LiveStatusPayload,
  ReplyContextPayload,
  ReplyPreviewPayload,
  ReplyRetrievalPayload,
  ReplyStylePayload,
  WorkspaceStatusPayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { buildReplyDraftScopeKey, type ChatWorkspaceState } from "@/stores/app-store";

import { EmptyState } from "./EmptyState";
import { WarningState } from "./WarningState";

interface ReplyPanelProps {
  reply: ReplyPreviewPayload | null;
  replyContext?: ReplyContextPayload | null;
  autopilot?: AutopilotPayload | null;
  freshness?: ChatFreshnessPayload | null;
  live?: LiveStatusPayload | null;
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

type PendingAutopilotChange = {
  scope: "global" | "chat";
  mode: string;
};

export function ReplyPanel({
  reply,
  replyContext = null,
  autopilot = null,
  freshness = null,
  live = null,
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
  const suggestion = safeReply?.suggestion ?? null;
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
        id: index === 0 ? "primary" : `variant-${index}`,
        label: index === 0 ? "Рекомендуемый" : `Вариант ${index + 1}`,
        description: index === 0 ? "Главный вариант для текущего фокуса." : "Запасная формулировка.",
        text,
      }));
  }, [isNoReply, suggestion]);

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showDebug, setShowDebug] = useState(false);
  const [showAutopilotDetails, setShowAutopilotDetails] = useState(false);
  const [draftText, setDraftText] = useState("");
  const [pendingAutopilotChange, setPendingAutopilotChange] = useState<PendingAutopilotChange | null>(null);

  const selectedReply = replyOptions[selectedIndex]?.text || "";
  const selectedVariant = replyOptions[selectedIndex] || null;
  const primaryVariant = replyOptions.find((item) => item.id === "primary") || replyOptions[0] || null;
  const secondaryVariants = buildSecondaryVariants(replyOptions, primaryVariant?.id ?? null);
  const shortVariant = replyOptions.find((item) => item.id === "short") || null;
  const softVariant = replyOptions.find((item) => item.id === "soft") || null;
  const ownerStyleVariant = replyOptions.find((item) => isOwnerStyleVariant(item.id)) || null;
  const triggerPreview = buildTriggerPreview(contextSourceSenderName, contextSourceMessagePreview);
  const llmDebug = suggestion?.llmDebug ?? null;
  const llmDecisionReason = llmDebug?.decisionReason ?? null;
  const llmStatusLabel = suggestion?.llmStatus?.label || "без ИИ";
  const llmDisplayLabel = friendlyLlmStatusLabel(suggestion?.llmStatus?.mode, llmStatusLabel);
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
  const autopilotMode = safeAutopilot?.mode || "off";
  const autopilotEffectiveMode = safeAutopilot?.effectiveMode || autopilotMode;
  const autopilotAllowed = Boolean(safeAutopilot?.autopilotAllowed ?? safeAutopilot?.allowed);
  const autopilotBlockedReason = safeAutopilot?.decision.reason || safeAutopilot?.state?.reason || null;
  const autopilotReasonCode = safeAutopilot?.decision.reasonCode || safeAutopilot?.state?.reasonCode || null;
  const freshnessCopy = buildFreshnessCopy(freshness, live, workspaceStatus);
  const liveCopy = buildLiveCopy(live);
  const workspaceCopy = buildWorkspaceCopy(workspaceStatus);
  const autopilotCopy = buildAutopilotCopy(safeAutopilot);

  useEffect(() => {
    setSelectedIndex(0);
    setShowDebug(false);
    setShowAutopilotDetails(false);
    setPendingAutopilotChange(null);
  }, [contextSourceMessageId, contextSourceMessagePreview, suggestion?.replyText]);

  useEffect(() => {
    const activeDraft = hasActiveDraft ? workflowState?.draftText || "" : "";
    setDraftText(activeDraft || selectedReply || "");
  }, [hasActiveDraft, selectedReply, workflowState?.draftScopeKey, workflowState?.draftText]);

  const sendDisabledReason =
    safeReply?.actions.disabledReason
    || workspaceStatus?.sendDisabledReason
    || (workspaceStatus?.availability.sendAvailable === false ? "Отправка сейчас недоступна." : null)
    || "Отправка сейчас недоступна.";
  const sendAllowed = Boolean(
    safeReply?.actions.send
      && (workspaceStatus?.availability.sendAvailable ?? true)
      && !isNoReply,
  );
  const hasContextOnlyWorkspace = Boolean(replyContext?.available && !suggestion);
  const replyStatus = buildReplyStatus({
    isNoReply,
    sendAllowed,
    sendStatus,
    autopilotPending: Boolean(autopilotPending?.status === "awaiting_confirmation"),
    suggestionExists: Boolean(suggestion),
    reason: contextReplyOpportunityReason || suggestion?.reasonShort || null,
  });
  const llmTone: UiTone =
    suggestion?.llmStatus?.mode === "fallback"
      ? "warning"
      : suggestion?.llmStatus?.mode === "rejected_by_guardrails"
        ? "danger"
        : suggestion?.llmStatus?.mode === "llm_refine"
          ? "success"
          : "muted";

  const requestGlobalAutopilotMode = (mode: string) => {
    if (mode === (safeAutopilot?.globalMode || "off")) {
      return;
    }
    if (mode === "autopilot") {
      setPendingAutopilotChange({ scope: "global", mode });
      return;
    }
    setPendingAutopilotChange(null);
    onUpdateAutopilotGlobal({ mode });
  };

  const requestChatAutopilotMode = (mode: string) => {
    const currentMode = autopilotMode === "confirm" ? "semi_auto" : autopilotMode;
    if (mode === currentMode) {
      return;
    }
    if (mode === "autopilot") {
      setPendingAutopilotChange({ scope: "chat", mode });
      return;
    }
    setPendingAutopilotChange(null);
    onUpdateChatAutopilot({ mode });
  };

  const confirmAutopilotChange = () => {
    if (!pendingAutopilotChange) {
      return;
    }
    if (pendingAutopilotChange.scope === "global") {
      onUpdateAutopilotGlobal({ mode: pendingAutopilotChange.mode });
    } else {
      onUpdateChatAutopilot({ mode: pendingAutopilotChange.mode });
    }
    setPendingAutopilotChange(null);
  };

  if (loading && !reply) {
    return (
      <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[22px] border border-white/7 bg-white/[0.035]">
        <div className="border-b border-white/7 px-4 py-3">
          <div className="text-base font-semibold text-white">Панель ответа</div>
        </div>
        <div className="flex flex-1 flex-col gap-4 px-4 py-4">
          <ReplyPanelSkeleton />
        </div>
      </section>
    );
  }

  if (errorMessage) {
    return (
      <WarningState
        title="Панель ответа не загрузилась"
        description={`Что случилось: ${errorMessage}. Что сделать: обнови чат или проверь локальный bridge.`}
        action={
          <div>
            <Button variant="outline" onClick={onRefresh} disabled={refreshing}>
              {refreshing ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
              {refreshing ? "Обновляю" : "Повторить"}
            </Button>
          </div>
        }
      />
    );
  }

  if (!reply) {
    return (
      <EmptyState
        title="Выбери чат"
        description="Здесь появятся статус ответа, рекомендуемый текст, черновик, отправка и безопасные настройки автопилота."
      />
    );
  }

  if (!safeReply) {
    return (
      <WarningState
        title="Ответ пришёл в неожиданном формате"
        description="Что это значит: desktop не может безопасно показать данные bridge. Что сделать: обнови чат или перезапусти локальный bridge."
        action={
          <div>
            <Button variant="outline" onClick={onRefresh} disabled={refreshing}>
              {refreshing ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
              {refreshing ? "Обновляю" : "Повторить"}
            </Button>
          </div>
        }
      />
    );
  }

  if (!suggestion) {
    if (hasContextOnlyWorkspace) {
      return (
        <ReplyPanelFrame
          title="Панель ответа"
          status={buildContextOnlyStatus(workspaceStatus)}
          refreshing={refreshing}
          onRefresh={onRefresh}
        >
          <StatusTile icon={<FileText />} status={workspaceCopy} />
          <StatusTile icon={<Sparkles />} status={{
            label: contextFocusLabel || "контекст найден",
            detail: contextFocusReason || contextReplyOpportunityReason || "Astra видит опорный сигнал, но готовый ответ сейчас не собран.",
            tone: "info",
          }} />
          {triggerPreview ? (
            <div className="rounded-[18px] border border-white/8 bg-black/16 px-4 py-3 text-sm leading-6 text-slate-200">
              <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Опорный сигнал</div>
              <div className="mt-2">{triggerPreview}</div>
            </div>
          ) : null}
          <div className="rounded-[18px] border border-amber-300/14 bg-amber-300/8 px-4 py-3 text-sm leading-6 text-amber-50">
            Что это значит: можно читать контекст, но отправлять готовый ответ пока нельзя. Что нажать дальше:
            обнови чат или проверь доступность ИИ/отправки.
          </div>
          <DetailsBlock
            open={showDebug}
            onToggle={() => setShowDebug((current) => !current)}
            title="Отладка / детали"
            summary={safeReply.kind}
          >
            <div>Источник контекста: {replyContext?.sourceBackend || "не указан"}</div>
            <div className="mt-2">Фокус: {contextFocusLabel || "нет"}</div>
            <div className="mt-2">Причина: {contextFocusReason || contextReplyOpportunityReason || "нет"}</div>
            <div className="mt-2">Сообщение: {contextSourceMessageKey || contextSourceMessageId || "нет"}</div>
            <div className="mt-2">Ограничение отправки: {sendDisabledReason}</div>
          </DetailsBlock>
        </ReplyPanelFrame>
      );
    }

    return (
      <WarningState
        title="Ответ пока не собран"
        description={safeReply.errorMessage || "Astra не смогла предложить ответ для выбранного контекста. Обнови чат, чтобы пересобрать панель."}
        action={
          <div>
            <Button variant="outline" onClick={onRefresh} disabled={refreshing}>
              {refreshing ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
              {refreshing ? "Обновляю" : "Пересобрать"}
            </Button>
          </div>
        }
      />
    );
  }

  return (
    <ReplyPanelFrame
      title="Панель ответа"
      status={replyStatus}
      refreshing={refreshing}
      onRefresh={onRefresh}
      badges={
        <>
          <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/10">
            уверенность {formatConfidence(suggestion.confidence)}
          </Badge>
          <Badge variant="outline" className={cn("border-0 ring-1", toneBadgeClasses(llmTone))}>
            ИИ: {llmDisplayLabel}
          </Badge>
        </>
      }
    >
      <section className="rounded-[20px] border border-cyan-300/12 bg-cyan-400/8 p-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium text-cyan-100">
            <Sparkles />
            {isNoReply ? "Рекомендация Astra" : "Главный вариант"}
          </div>
          {!isNoReply && primaryVariant ? (
            <Badge variant="outline" className="border-0 bg-white/8 text-white ring-1 ring-white/10">
              рекомендуется
            </Badge>
          ) : null}
        </div>
        <div className="text-lg font-semibold tracking-tight text-white">
          {isNoReply ? "Сейчас лучше не отвечать" : contextFocusLabel || "Можно ответить"}
        </div>
        <div className="mt-2 text-sm leading-6 text-cyan-50/85">
          {compactReason(contextFocusReason || contextReplyOpportunityReason || suggestion.reasonShort)}
        </div>

        {triggerPreview ? (
          <div className="mt-3 rounded-[16px] border border-white/8 bg-black/16 px-3 py-2 text-sm leading-6 text-slate-200">
            <span className="text-slate-500">Опорный сигнал: </span>
            {triggerPreview}
          </div>
        ) : null}

        {isNoReply ? (
          <div className="mt-3 rounded-[16px] border border-amber-300/16 bg-amber-300/8 px-3 py-2 text-sm leading-6 text-amber-50">
            {suggestion.alternativeAction || "Подожди нового сигнала или обнови контекст позже."}
          </div>
        ) : primaryVariant ? (
          <button
            type="button"
            className={cn(
              "mt-3 w-full rounded-[18px] border px-4 py-3 text-left transition-all hover:border-cyan-200/24 hover:bg-cyan-300/10 active:translate-y-px",
              selectedVariant?.id === primaryVariant.id
                ? "border-cyan-200/24 bg-cyan-300/10"
                : "border-white/8 bg-black/16",
            )}
            onClick={() => setSelectedIndex(replyOptions.findIndex((item) => item.id === primaryVariant.id))}
          >
            <div className="mb-2 text-xs text-slate-400">{primaryVariant.description || "Готовый текст ответа."}</div>
            <VariantTextPreview text={primaryVariant.text} ownerStyle={isOwnerStyleVariant(primaryVariant.id)} />
          </button>
        ) : null}
      </section>

      {!isNoReply && secondaryVariants.length > 0 ? (
        <section className="rounded-[20px] border border-white/8 bg-black/16 p-4">
          <div className="mb-3 text-sm font-medium text-white">Варианты ответа</div>
          <div className="grid gap-2">
            {secondaryVariants.map((item) => {
              const index = replyOptions.findIndex((variant) => variant.id === item.id);
              return (
                <button
                  key={item.id}
                  type="button"
                  className={cn(
                    "rounded-[16px] border px-3 py-2.5 text-left text-sm leading-5 transition-all hover:border-cyan-300/16 hover:bg-white/[0.045] active:translate-y-px",
                    selectedIndex === index
                      ? "border-cyan-300/18 bg-cyan-300/8 text-cyan-50"
                      : "border-white/7 bg-white/[0.025] text-slate-200",
                  )}
                  onClick={() => setSelectedIndex(index)}
                >
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="font-medium">{friendlyVariantLabel(item.label, item.id)}</span>
                    {selectedIndex === index ? <span className="text-xs text-cyan-100">выбран</span> : null}
                  </div>
                  <VariantTextPreview text={item.text} ownerStyle={isOwnerStyleVariant(item.id)} compact />
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      {!isNoReply ? (
        <section className="rounded-[20px] border border-white/8 bg-black/16 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-medium text-white">
              <WandSparkles />
              Действия с текстом
            </div>
            {refreshing ? <span className="text-xs text-cyan-100">пересобираю...</span> : null}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Button
              variant="outline"
              className="border-white/8 bg-black/16 text-slate-100"
              onClick={() => selectVariantById(replyOptions, "short", setSelectedIndex)}
              disabled={!shortVariant}
            >
              <Minimize2 data-icon="inline-start" />
              Сделать короче
            </Button>
            <Button
              variant="outline"
              className="border-white/8 bg-black/16 text-slate-100"
              onClick={() => selectVariantById(replyOptions, "soft", setSelectedIndex)}
              disabled={!softVariant}
            >
              <Heart data-icon="inline-start" />
              Мягче
            </Button>
            <Button
              variant="outline"
              className="border-white/8 bg-black/16 text-slate-100"
              onClick={() => selectVariantById(replyOptions, "owner_style", setSelectedIndex)}
              disabled={!ownerStyleVariant}
            >
              <MessageSquare data-icon="inline-start" />
              В моём стиле
            </Button>
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
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
              {refreshing ? "Пересобираю" : "Пересобрать"}
            </Button>
            <Button
              variant="outline"
              className="border-white/8 bg-black/16 text-slate-100"
              onClick={() => onMarkSent(contextSourceMessageId, contextSourceMessageKey)}
            >
              <CheckCheck data-icon="inline-start" />
              Уже отправлено
            </Button>
          </div>
        </section>
      ) : null}

      {!isNoReply ? (
        <section className="rounded-[20px] border border-white/8 bg-black/16 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
            <ShieldAlert />
            Черновик и отправка
          </div>

          <textarea
            value={draftText}
            onChange={(event) => setDraftText(event.target.value)}
            rows={4}
            className="min-h-24 w-full resize-y rounded-[16px] border border-white/8 bg-black/24 px-4 py-3 text-sm leading-6 text-slate-100 outline-none transition focus:border-cyan-300/24 focus:bg-black/32"
            placeholder="Вставь вариант, поправь формулировку и отправь явно."
          />
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Button
              variant="outline"
              className="border-white/8 bg-black/18 text-slate-100"
              onClick={() => onUseDraft(draftText, contextSourceMessageId, contextSourceMessageKey)}
              disabled={!draftText.trim()}
            >
              <FileText data-icon="inline-start" />
              Сохранить
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="w-full">
                  <Button
                    className="w-full bg-emerald-300 text-[#05111c] hover:bg-emerald-200"
                    onClick={() => onSend(draftText, contextSourceMessageId, contextSourceMessageKey, currentDraftScopeKey)}
                    disabled={!sendAllowed || !draftText.trim() || sending}
                    aria-busy={sending}
                  >
                    {sending ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Send data-icon="inline-start" />}
                    {sending ? "Отправляю" : "Отправить"}
                  </Button>
                </span>
              </TooltipTrigger>
              {!sendAllowed ? <TooltipContent>{sendDisabledReason}</TooltipContent> : null}
            </Tooltip>
          </div>

          {sendStatus ? <SendStatusCard sendStatus={sendStatus} /> : null}
          <DraftState
            hasActiveDraft={hasActiveDraft}
            hasStaleDraft={hasStaleDraft}
            workflowState={workflowState}
            onCopy={onCopy}
            onClearDraft={onClearDraft}
          />
        </section>
      ) : null}

      <section className="grid gap-2">
        <StatusTile icon={<Sparkles />} status={freshnessCopy} />
        <StatusTile icon={live?.paused ? <Pause /> : <RefreshCcw />} status={liveCopy} />
        <StatusTile icon={<ShieldAlert />} status={autopilotCopy} />
      </section>

      <AutopilotControls
        autopilot={safeAutopilot}
        autopilotMode={autopilotMode}
        autopilotEffectiveMode={autopilotEffectiveMode}
        autopilotAllowed={autopilotAllowed}
        autopilotBlockedReason={autopilotBlockedReason}
        pendingAutopilotChange={pendingAutopilotChange}
        autopilotUpdating={autopilotUpdating}
        sending={sending}
        sendAllowed={sendAllowed}
        contextSourceMessageKey={contextSourceMessageKey}
        currentDraftScopeKey={currentDraftScopeKey}
        onRequestGlobalMode={requestGlobalAutopilotMode}
        onRequestChatMode={requestChatAutopilotMode}
        onConfirmChange={confirmAutopilotChange}
        onCancelChange={() => setPendingAutopilotChange(null)}
        onUpdateAutopilotGlobal={onUpdateAutopilotGlobal}
        onUpdateChatAutopilot={onUpdateChatAutopilot}
        onConfirmAutopilot={onConfirmAutopilot}
        onEmergencyStop={onEmergencyStop}
        onUseDraft={(text, sourceMessageId, sourceMessageKey) => {
          setDraftText(text);
          onUseDraft(text, sourceMessageId, sourceMessageKey);
        }}
        onSend={onSend}
      />

      <DetailsBlock
        open={showDebug}
        onToggle={() => setShowDebug((current) => !current)}
        title="Отладка / детали"
        summary={llmDisplayLabel}
      >
        <div>Режим ИИ: {suggestion.llmStatus?.mode || "deterministic"}</div>
        <div className="mt-2">Trigger backend: {triggerBackendLabel || "не указан"}</div>
        <div className="mt-2">Trigger key: {triggerDetails?.messageKey || "нет"}</div>
        <div className="mt-2">Focus: {contextFocusLabel || "нет"}</div>
        <div className="mt-2">Opportunity: {contextReplyOpportunityMode || "hold"}</div>
        <div className="mt-2">Workspace: {workspaceStatus?.source || "нет"} / {workspaceStatus?.messageSource.backend || "нет"}</div>
        <div className="mt-2">Live reason code: {live?.reasonCode || "none"}</div>
        <div className="mt-2">Autopilot reason code: {autopilotReasonCode || "none"}</div>
        <div className="mt-2">
          Причина:{" "}
          {llmDecisionReason?.detail
            || suggestion.llmStatus?.detail
            || "LLM-улучшение не запрашивалось, используется детерминированная база."}
        </div>
        {contextReplyOpportunityReason ? (
          <div className="mt-2">Почему reply уместен: {contextReplyOpportunityReason}</div>
        ) : null}
        {retrievalDetails ? <div className="mt-2">Retrieval: {retrievalSummary}</div> : null}
        {styleSummary ? <div className="mt-2">Style: {styleSummary}</div> : null}
        {fallbackDetails?.reason ? <div className="mt-2">Fallback: {fallbackDetails.reason}</div> : null}
        {llmDecisionReason?.flags.length ? (
          <div className="mt-2">Ограничители: {llmDecisionReason.flags.join(" • ")}</div>
        ) : null}
        {retrievalDetails?.hits.length ? (
          <>
            <div className="mt-4 text-[11px] uppercase tracking-[0.2em] text-slate-500">Похожие реальные ответы</div>
            <div className="mt-2 flex flex-col gap-2">
              {retrievalDetails.hits.slice(0, 3).map((item) => (
                <div key={`${item.id}-${item.score ?? "score"}`} className="rounded-[14px] border border-white/6 bg-black/18 px-3 py-3">
                  <div className="text-xs text-slate-400">
                    {item.chatTitle}
                    {item.score !== null ? ` • score ${item.score.toFixed(2)}` : ""}
                  </div>
                  <div className="mt-1 text-slate-200">Входящее: {item.inboundText}</div>
                  <div className="mt-1 text-slate-100">Исходящее: {item.outboundText}</div>
                  {item.reasons.length ? <div className="mt-1 text-xs text-slate-400">{item.reasons.join(" • ")}</div> : null}
                </div>
              ))}
            </div>
          </>
        ) : null}
        <div className="mt-4 text-[11px] uppercase tracking-[0.2em] text-slate-500">Базовый вариант</div>
        <div className="mt-2 whitespace-pre-wrap rounded-[14px] border border-white/6 bg-black/18 px-3 py-3 text-slate-100">
          {llmDebug?.baselineText || suggestion.replyText || "Нет базового варианта."}
        </div>
        <div className="mt-4 text-[11px] uppercase tracking-[0.2em] text-slate-500">Сырой LLM-кандидат</div>
        <div className="mt-2 whitespace-pre-wrap rounded-[14px] border border-white/6 bg-black/18 px-3 py-3 text-slate-100">
          {llmDebug?.rawCandidate || "Кандидат не сохранялся: LLM-улучшение не применялось или провайдер не вернул текст."}
        </div>
      </DetailsBlock>

      {safeAutopilot?.journal.length ? (
        <DetailsBlock
          open={showAutopilotDetails}
          onToggle={() => setShowAutopilotDetails((current) => !current)}
          title="Журнал автопилота"
          summary={`${safeAutopilot.journal.length} событий`}
        >
          <div className="flex flex-col gap-2">
            {safeAutopilot.journal.slice(0, 6).map((item, index) => (
              <div key={`${item.timestamp || "event"}-${index}`} className="rounded-[14px] border border-white/6 bg-black/18 px-3 py-3">
                <div className="text-slate-100">{item.message || item.status || "событие"}</div>
                <div className="mt-1 text-xs text-slate-400">
                  {item.timestamp ? formatDateTime(item.timestamp) : "без времени"}
                  {item.reason ? ` • ${item.reason}` : ""}
                  {item.reasonCode || item.reason_code ? ` • ${item.reasonCode || item.reason_code}` : ""}
                </div>
              </div>
            ))}
          </div>
        </DetailsBlock>
      ) : null}
    </ReplyPanelFrame>
  );
}

function ReplyPanelFrame({
  title,
  status,
  badges,
  refreshing,
  onRefresh,
  children,
}: {
  title: string;
  status: UiStatusCopy;
  badges?: ReactNode;
  refreshing: boolean;
  onRefresh: () => void;
  children: ReactNode;
}) {
  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[22px] border border-white/7 bg-white/[0.035]">
      <div className="border-b border-white/7 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Astra</div>
            <div className="text-base font-semibold text-white">{title}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge variant="outline" className={cn("border-0 ring-1", toneBadgeClasses(status.tone))}>
                {status.label}
              </Badge>
              {badges}
            </div>
          </div>
          <Button
            variant="outline"
            size="icon-sm"
            className="border-white/8 bg-black/18 text-slate-100"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label={refreshing ? "Пересобираю панель ответа" : "Пересобрать панель ответа"}
            title={refreshing ? "Пересобираю панель ответа" : "Пересобрать панель ответа"}
          >
            {refreshing ? <LoaderCircle className="animate-spin" /> : <RefreshCcw />}
          </Button>
        </div>
        <div className="mt-2 text-xs leading-5 text-slate-400">{status.detail}</div>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-3 px-4 py-4">{children}</div>
      </ScrollArea>
    </section>
  );
}

function StatusTile({ icon, status }: { icon: ReactNode; status: UiStatusCopy }) {
  return (
    <div className={cn("rounded-[18px] border px-4 py-3", tonePanelClasses(status.tone))}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-white/8 text-slate-100">
          {icon}
        </div>
        <div className="min-w-0">
          <div className="text-sm font-medium text-white">{status.label}</div>
          <div className="mt-1 text-xs leading-5 text-slate-300">{status.detail}</div>
        </div>
      </div>
    </div>
  );
}

function SendStatusCard({
  sendStatus,
}: {
  sendStatus: NonNullable<ReplyPanelProps["sendStatus"]>;
}) {
  return (
    <div
      className={cn(
        "mt-3 rounded-[16px] border px-4 py-3 text-sm leading-6",
        sendStatus.tone === "success"
          ? "border-emerald-300/12 bg-emerald-300/8 text-emerald-50"
          : sendStatus.tone === "pending"
            ? "border-cyan-300/12 bg-cyan-300/8 text-cyan-50"
            : sendStatus.tone === "warning"
              ? "border-amber-300/12 bg-amber-300/8 text-amber-50"
              : "border-rose-300/12 bg-rose-400/8 text-rose-50",
      )}
    >
      <div className="flex items-center gap-2 font-medium">
        {sendStatus.tone === "pending" ? <LoaderCircle className="size-4 animate-spin" /> : null}
        {sendStatus.message}
      </div>
      <div className="mt-1 text-xs opacity-80">
        {formatSendChannel(sendStatus.backend)}
        {" • "}
        {formatDateTime(sendStatus.timestamp)}
      </div>
    </div>
  );
}

function DraftState({
  hasActiveDraft,
  hasStaleDraft,
  workflowState,
  onCopy,
  onClearDraft,
}: {
  hasActiveDraft: boolean;
  hasStaleDraft: boolean;
  workflowState: ChatWorkspaceState | null;
  onCopy: (text: string) => void;
  onClearDraft: () => void;
}) {
  if (hasActiveDraft) {
    return (
      <div className="mt-3 rounded-[16px] border border-amber-300/12 bg-amber-300/8 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-medium text-amber-50">Локальный черновик сохранён</div>
          <div className="text-xs text-amber-100/70">
            {workflowState?.draftUpdatedAt ? formatDateTime(workflowState.draftUpdatedAt) : "сейчас"}
          </div>
        </div>
        <div className="mt-2 line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-slate-100">
          {workflowState?.draftText}
        </div>
        <div className="mt-3 flex gap-2">
          <Button variant="outline" className="border-white/8 bg-black/18 text-slate-100" onClick={() => onCopy(workflowState?.draftText || "")}>
            <Copy data-icon="inline-start" />
            Скопировать
          </Button>
          <Button variant="outline" className="border-white/8 bg-black/18 text-slate-100" onClick={onClearDraft}>
            Очистить
          </Button>
        </div>
      </div>
    );
  }

  if (hasStaleDraft) {
    return (
      <div className="mt-3 rounded-[16px] border border-amber-300/12 bg-amber-300/8 px-4 py-3">
        <div className="text-sm font-medium text-amber-50">Черновик устарел для текущего фокуса</div>
        <div className="mt-2 text-sm leading-6 text-slate-100">
          Старый текст скрыт, потому что текущий ответ опирается на другой сигнал.
        </div>
        <div className="mt-3 flex gap-2">
          <Button variant="outline" className="border-white/8 bg-black/18 text-slate-100" onClick={() => onCopy(workflowState?.draftText || "")}>
            <Copy data-icon="inline-start" />
            Скопировать старый черновик
          </Button>
          <Button variant="outline" className="border-white/8 bg-black/18 text-slate-100" onClick={onClearDraft}>
            Очистить
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-[16px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-300">
      Сохрани черновик, чтобы не потерять выбранный вариант при обновлении.
    </div>
  );
}

function AutopilotControls({
  autopilot,
  autopilotMode,
  autopilotEffectiveMode,
  autopilotAllowed,
  autopilotBlockedReason,
  pendingAutopilotChange,
  autopilotUpdating,
  sending,
  sendAllowed,
  contextSourceMessageKey,
  currentDraftScopeKey,
  onRequestGlobalMode,
  onRequestChatMode,
  onConfirmChange,
  onCancelChange,
  onUpdateAutopilotGlobal,
  onUpdateChatAutopilot,
  onConfirmAutopilot,
  onEmergencyStop,
  onUseDraft,
  onSend,
}: {
  autopilot: AutopilotPayload | null;
  autopilotMode: string;
  autopilotEffectiveMode: string;
  autopilotAllowed: boolean;
  autopilotBlockedReason: string | null;
  pendingAutopilotChange: PendingAutopilotChange | null;
  autopilotUpdating: boolean;
  sending: boolean;
  sendAllowed: boolean;
  contextSourceMessageKey: string | null;
  currentDraftScopeKey: string | null;
  onRequestGlobalMode: (mode: string) => void;
  onRequestChatMode: (mode: string) => void;
  onConfirmChange: () => void;
  onCancelChange: () => void;
  onUpdateAutopilotGlobal: ReplyPanelProps["onUpdateAutopilotGlobal"];
  onUpdateChatAutopilot: ReplyPanelProps["onUpdateChatAutopilot"];
  onConfirmAutopilot: ReplyPanelProps["onConfirmAutopilot"];
  onEmergencyStop: ReplyPanelProps["onEmergencyStop"];
  onUseDraft: (text: string, sourceMessageId: number | null, sourceMessageKey: string | null) => void;
  onSend: NonNullable<ReplyPanelProps["onSend"]>;
}) {
  if (!autopilot) {
    return (
      <section className="rounded-[20px] border border-white/8 bg-black/16 p-4 text-sm leading-6 text-slate-300">
        <div className="mb-2 flex items-center gap-2 font-medium text-white">
          <ShieldAlert />
          Автопилот
        </div>
        Состояние автопилота пока не пришло от bridge. Что нажать дальше: обнови чат.
      </section>
    );
  }

  const pending = autopilot.pendingDraft ?? null;
  const pendingId = pending?.executionId || pending?.id || null;
  const pendingText = pending?.text || "";

  return (
    <section className="rounded-[20px] border border-white/8 bg-black/16 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-white">
          <ShieldAlert />
          Безопасность автопилота
        </div>
        <Badge variant="outline" className={cn("border-0 ring-1", toneBadgeClasses(autopilotEffectiveMode === "autopilot" ? "danger" : autopilotEffectiveMode === "semi_auto" ? "warning" : autopilotEffectiveMode === "draft" ? "info" : "muted"))}>
          {formatAutopilotMode(autopilotEffectiveMode)}
        </Badge>
      </div>

      <div className={cn("rounded-[16px] border px-4 py-3", tonePanelClasses(autopilot.emergencyStop ? "danger" : autopilot.masterEnabled ? "success" : "muted"))}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Глобально</div>
            <div className="mt-1 text-sm font-medium text-white">
              {autopilot.emergencyStop
                ? "Экстренный стоп активен"
                : autopilot.masterEnabled
                  ? `Глобально: ${formatAutopilotMode(autopilot.globalMode)}`
                  : "Глобально выключено"}
            </div>
          </div>
          <Button
            variant="outline"
            className="border-rose-300/14 bg-rose-400/8 text-rose-50"
            disabled={autopilotUpdating || autopilot.emergencyStop}
            onClick={onEmergencyStop}
          >
            {autopilotUpdating ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <StopCircle data-icon="inline-start" />}
            Экстренный стоп
          </Button>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-2">
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Глобальный режим</span>
          <select
            value={autopilot.globalMode || "off"}
            disabled={autopilotUpdating || autopilot.emergencyStop}
            onChange={(event) => onRequestGlobalMode(event.target.value)}
            className="h-9 rounded-[14px] border border-white/8 bg-black/24 px-3 text-sm text-slate-100 outline-none transition focus:border-cyan-300/24 disabled:opacity-45"
          >
            <option value="off">Выключен</option>
            <option value="draft">Черновик</option>
            <option value="semi_auto">Полуавтомат</option>
            <option value="autopilot">Автопилот</option>
          </select>
        </label>

        <label className="flex flex-col gap-2">
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Режим чата</span>
          <select
            value={autopilotMode === "confirm" ? "semi_auto" : autopilotMode}
            disabled={autopilotUpdating}
            onChange={(event) => onRequestChatMode(event.target.value)}
            className="h-9 rounded-[14px] border border-white/8 bg-black/24 px-3 text-sm text-slate-100 outline-none transition focus:border-cyan-300/24 disabled:opacity-45"
          >
            <option value="off">Выключен</option>
            <option value="draft">Черновик</option>
            <option value="semi_auto">Полуавтомат</option>
            <option value="autopilot">Автопилот</option>
          </select>
        </label>
      </div>

      {pendingAutopilotChange ? (
        <div className="mt-3 rounded-[16px] border border-rose-300/16 bg-rose-400/8 px-4 py-3 text-sm leading-6 text-rose-50">
          <div className="font-medium">Подтверди включение автопилота</div>
          <div className="mt-1 text-rose-50/80">
            Это разрешит автоотправку в выбранной области. Нажми явное подтверждение, если это точно нужно.
          </div>
          <div className="mt-3 flex gap-2">
            <Button className="bg-rose-200 text-[#2a0707] hover:bg-rose-100" disabled={autopilotUpdating} onClick={onConfirmChange}>
              {autopilotUpdating ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <Power data-icon="inline-start" />}
              Включить автопилот
            </Button>
            <Button variant="outline" className="border-white/8 bg-black/18 text-slate-100" onClick={onCancelChange}>
              Отмена
            </Button>
          </div>
        </div>
      ) : null}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button
          variant="outline"
          className={cn("border-white/8 bg-black/18 text-slate-100", autopilot.trusted && "border-cyan-300/18 bg-cyan-300/10 text-cyan-50")}
          disabled={autopilotUpdating}
          onClick={() => onUpdateChatAutopilot?.({ trusted: !autopilot.trusted })}
        >
          {autopilot.trusted ? "Trusted включён" : "Trusted выключен"}
        </Button>
        <Button
          variant="outline"
          className={cn("border-white/8 bg-black/18 text-slate-100", autopilotAllowed && "border-emerald-300/18 bg-emerald-300/10 text-emerald-50")}
          disabled={autopilotUpdating}
          onClick={() => onUpdateChatAutopilot?.({ autopilot_allowed: !autopilotAllowed, allowed: !autopilotAllowed })}
        >
          {autopilotAllowed ? "Allowed включён" : "Allowed выключен"}
        </Button>
      </div>

      <div className="mt-3 rounded-[16px] border border-white/6 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-300">
        <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Последняя причина блокировки</div>
        <div className="mt-1 text-slate-100">{compactReason(autopilotBlockedReason, "Блокировки сейчас нет.")}</div>
        <div className="mt-2 text-xs text-slate-400">
          {autopilot.writeReady ? "Отправка технически доступна" : "Отправка закрыта"}
          {autopilot.cooldown.active ? ` • cooldown ${autopilot.cooldown.remainingSeconds}с` : ""}
        </div>
      </div>

      {pendingText ? (
        <div className="mt-3 rounded-[16px] border border-amber-300/12 bg-amber-300/8 px-4 py-3">
          <div className="mb-1 text-xs uppercase tracking-[0.2em] text-amber-100/70">
            {pending?.status === "awaiting_confirmation" ? "Ждёт подтверждения" : "Авточерновик"}
          </div>
          <div className="whitespace-pre-wrap text-sm leading-6 text-slate-100">{pendingText}</div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="outline"
              className="border-white/8 bg-black/18 text-slate-100"
              onClick={() => onUseDraft(
                pendingText,
                autopilot.decision.sourceMessageId,
                autopilot.decision.sourceMessageKey || contextSourceMessageKey,
              )}
            >
              В черновик
            </Button>
            {pending?.status === "awaiting_confirmation" ? (
              <Button
                className="bg-emerald-300 text-[#05111c] hover:bg-emerald-200"
                disabled={autopilotUpdating || sending}
                onClick={() => onConfirmAutopilot?.(pendingId)}
              >
                {autopilotUpdating || sending ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <Send data-icon="inline-start" />}
                Подтвердить отправку
              </Button>
            ) : (
              <Button
                className="bg-emerald-300 text-[#05111c] hover:bg-emerald-200"
                disabled={!sendAllowed || sending}
                onClick={() => onSend(
                  pendingText,
                  autopilot.decision.sourceMessageId,
                  autopilot.decision.sourceMessageKey || contextSourceMessageKey,
                  autopilot.decision.draftScopeKey || currentDraftScopeKey,
                )}
              >
                {sending ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <Send data-icon="inline-start" />}
                {sending ? "Отправляю" : "Отправить вручную"}
              </Button>
            )}
          </div>
        </div>
      ) : null}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button
          variant="outline"
          className="border-white/8 bg-black/18 text-slate-100"
          disabled={autopilotUpdating}
          onClick={() => onUpdateAutopilotGlobal?.({ autopilot_paused: !autopilot.autopilotPaused })}
        >
          {autopilotUpdating ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <Pause data-icon="inline-start" />}
          {autopilot.autopilotPaused ? "Снять паузу" : "Пауза"}
        </Button>
        <Button
          variant="outline"
          className="border-rose-300/14 bg-rose-400/8 text-rose-50"
          disabled={autopilotUpdating}
          onClick={() => onUpdateChatAutopilot?.({ trusted: false, allowed: false, autopilot_allowed: false, mode: "off" })}
        >
          <StopCircle data-icon="inline-start" />
          Стоп для чата
        </Button>
      </div>
    </section>
  );
}

function DetailsBlock({
  open,
  onToggle,
  title,
  summary,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  title: string;
  summary: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[20px] border border-white/8 bg-black/16">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-white/[0.035]"
        onClick={onToggle}
      >
        <div className="flex items-center gap-2 text-sm font-medium text-white">
          <Bug className="size-4" />
          {title}
        </div>
        <div className="inline-flex items-center gap-2 text-xs text-slate-400">
          {summary}
          {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
        </div>
      </button>
      {open ? (
        <div className="max-h-[360px] overflow-auto border-t border-white/6 px-4 py-4 text-sm leading-6 text-slate-300">
          {children}
        </div>
      ) : null}
    </section>
  );
}

function buildReplyStatus({
  isNoReply,
  sendAllowed,
  sendStatus,
  autopilotPending,
  suggestionExists,
  reason,
}: {
  isNoReply: boolean;
  sendAllowed: boolean;
  sendStatus: ReplyPanelProps["sendStatus"];
  autopilotPending: boolean;
  suggestionExists: boolean;
  reason: string | null;
}): UiStatusCopy {
  if (sendStatus?.tone === "success") {
    return { label: "отправлено", detail: sendStatus.message, tone: "success" };
  }
  if (sendStatus?.tone === "error") {
    return { label: "ошибка", detail: sendStatus.message, tone: "danger" };
  }
  if (sendStatus?.tone === "pending") {
    return { label: "отправляю", detail: sendStatus.message, tone: "info" };
  }
  if (autopilotPending) {
    return {
      label: "ждёт подтверждение",
      detail: "Полуавтомат подготовил текст, но отправит его только после явного подтверждения.",
      tone: "warning",
    };
  }
  if (isNoReply) {
    return {
      label: "лучше не отвечать",
      detail: compactReason(reason, "Явного повода писать сейчас нет."),
      tone: "warning",
    };
  }
  if (!suggestionExists) {
    return {
      label: "ответ не собран",
      detail: "Есть контекст, но нет готового текста ответа.",
      tone: "warning",
    };
  }
  return {
    label: sendAllowed ? "можно ответить" : "можно подготовить",
    detail: sendAllowed
      ? compactReason(reason, "Есть понятный повод ответить.")
      : "Текст можно подготовить, но отправка сейчас закрыта.",
    tone: sendAllowed ? "success" : "warning",
  };
}

function buildContextOnlyStatus(workspaceStatus: WorkspaceStatusPayload | null | undefined): UiStatusCopy {
  if (workspaceStatus?.availability.sendAvailable === false) {
    return {
      label: "ответ не собран",
      detail: "Контекст найден, но готовый текст или отправка сейчас недоступны.",
      tone: "warning",
    };
  }
  return {
    label: "контекст найден",
    detail: "Astra видит опорный сигнал, но готовый ответ пока не собран.",
    tone: "info",
  };
}

function buildSecondaryVariants(
  variants: Array<{ id: string; label: string; description: string; text: string }>,
  primaryId: string | null,
) {
  const preferred = ["short", "soft", "owner_style", "style"]
    .map((id) => variants.find((item) => item.id === id))
    .filter((item): item is { id: string; label: string; description: string; text: string } => Boolean(item));
  const fallback = variants.filter((item) => item.id !== primaryId && !preferred.some((preferredItem) => preferredItem.id === item.id));
  return [...preferred, ...fallback].slice(0, 3);
}

function VariantTextPreview({
  text,
  ownerStyle,
  compact = false,
}: {
  text: string;
  ownerStyle: boolean;
  compact?: boolean;
}) {
  const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  if (ownerStyle && lines.length > 1) {
    return (
      <div className={cn("flex flex-col items-start", compact ? "gap-1.5" : "gap-2")}>
        {lines.slice(0, compact ? 4 : 6).map((line, index) => (
          <span
            key={`${line}-${index}`}
            className={cn(
              "max-w-full rounded-[12px] border border-cyan-200/10 bg-cyan-200/8 px-2.5 py-1 text-slate-50",
              compact ? "line-clamp-1 text-xs leading-5" : "text-sm leading-6",
            )}
          >
            {line}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className={cn("whitespace-pre-wrap text-slate-50", compact ? "line-clamp-2 text-sm leading-5" : "text-sm leading-6")}>
      {text}
    </div>
  );
}

function friendlyVariantLabel(label: string, id: string): string {
  if (id === "short") {
    return "Короткий";
  }
  if (id === "soft") {
    return "Мягкий";
  }
  if (isOwnerStyleVariant(id)) {
    return "В моём стиле";
  }
  return label || "Вариант";
}

function isOwnerStyleVariant(id: string | null | undefined): boolean {
  return id === "owner_style" || id === "style";
}

function selectVariantById(
  variants: Array<{ id: string; label: string; description: string; text: string }>,
  id: "short" | "soft" | "owner_style",
  setSelectedIndex: (value: number) => void,
) {
  const index = variants.findIndex((item) => (id === "owner_style" ? isOwnerStyleVariant(item.id) : item.id === id));
  if (index >= 0) {
    setSelectedIndex(index);
  }
}

function friendlyLlmStatusLabel(mode: string | null | undefined, label: string): string {
  if (mode === "fallback" || mode === "rejected_by_guardrails") {
    return "резервный вариант";
  }
  return label;
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

function formatSendChannel(backend: string | null): string {
  if (!backend) {
    return "канал отправки не выбран";
  }
  if (backend === "new" || backend.includes("runtime")) {
    return "основной Telegram";
  }
  if (backend === "legacy" || backend.includes("legacy") || backend.includes("fallback")) {
    return "legacy режим";
  }
  return "канал отправки готов";
}

function buildRetrievalSummary(
  retrieval: ReplyRetrievalPayload | null | undefined,
): string {
  if (!retrieval || !retrieval.used) {
    return "Похожие ответы не повлияли на текст.";
  }

  const parts = [
    retrieval.strategyBias ? `bias ${retrieval.strategyBias}` : null,
    retrieval.lengthHint ? `длина ${retrieval.lengthHint}` : null,
    retrieval.rhythmHint ? `ритм ${retrieval.rhythmHint}` : null,
    retrieval.messageCountHint ? `${retrieval.messageCountHint} репл.` : null,
    retrieval.styleMarkers?.length ? `маркеры ${retrieval.styleMarkers.slice(0, 3).join(", ")}` : null,
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
      <Skeleton className="h-24 rounded-[20px] bg-white/10" />
      <Skeleton className="h-40 rounded-[20px] bg-white/10" />
      <div className="grid grid-cols-2 gap-2">
        <Skeleton className="h-9 rounded-xl bg-white/10" />
        <Skeleton className="h-9 rounded-xl bg-white/10" />
        <Skeleton className="h-9 rounded-xl bg-white/10" />
        <Skeleton className="h-9 rounded-xl bg-white/10" />
      </div>
      <Skeleton className="h-32 rounded-[20px] bg-white/10" />
    </div>
  );
}
