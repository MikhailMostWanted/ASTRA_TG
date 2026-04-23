import type {
  AutopilotPayload,
  ChatFreshnessPayload,
  ReplyPreviewPayload,
  ReplySuggestion,
  ScreenId,
} from "@/lib/types";

const SCREEN_IDS: ScreenId[] = [
  "dashboard",
  "chats",
  "sources",
  "fullaccess",
  "memory",
  "digest",
  "reminders",
  "logs",
];

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function safeArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

export function safeString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function safeStringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function safeBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function safeNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function safeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

export function safeRecord<T = unknown>(value: unknown): Record<string, T> {
  return isPlainObject(value) ? (value as Record<string, T>) : {};
}

export function coerceScreenId(value: unknown): ScreenId {
  return typeof value === "string" && SCREEN_IDS.includes(value as ScreenId)
    ? (value as ScreenId)
    : "dashboard";
}

export function extractErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  return fallback;
}

export function normalizeReplySuggestion(value: unknown): ReplySuggestion | null {
  if (!isPlainObject(value)) {
    return null;
  }

  const llmStatus = isPlainObject(value.llmStatus) ? value.llmStatus : null;
  const llmDebug = isPlainObject(value.llmDebug) ? value.llmDebug : null;
  const decisionReason = llmDebug && isPlainObject(llmDebug.decisionReason) ? llmDebug.decisionReason : null;
  const rawVariants = Array.isArray(value.variants) ? value.variants : [];

  return {
    baseReplyText: safeStringOrNull(value.baseReplyText),
    replyMessages: safeStringArray(value.replyMessages),
    finalReplyMessages: safeStringArray(value.finalReplyMessages),
    replyText: safeStringOrNull(value.replyText),
    styleProfileKey: safeStringOrNull(value.styleProfileKey),
    styleSource: safeStringOrNull(value.styleSource),
    styleNotes: safeStringArray(value.styleNotes),
    personaApplied: safeBoolean(value.personaApplied),
    personaNotes: safeStringArray(value.personaNotes),
    guardrailFlags: safeStringArray(value.guardrailFlags),
    reasonShort: safeStringOrNull(value.reasonShort),
    riskLabel: safeStringOrNull(value.riskLabel),
    confidence: safeNumberOrNull(value.confidence),
    strategy: safeStringOrNull(value.strategy),
    sourceMessageId: safeNumberOrNull(value.sourceMessageId),
    chatId: safeNumberOrNull(value.chatId),
    situation: safeStringOrNull(value.situation),
    sourceMessagePreview: safeStringOrNull(value.sourceMessagePreview),
    focusLabel: safeStringOrNull(value.focusLabel),
    focusReason: safeStringOrNull(value.focusReason),
    replyOpportunityMode: safeStringOrNull(value.replyOpportunityMode),
    replyOpportunityReason: safeStringOrNull(value.replyOpportunityReason),
    fewShotFound: safeBoolean(value.fewShotFound),
    fewShotMatchCount: safeNumberOrNull(value.fewShotMatchCount) ?? 0,
    fewShotNotes: safeStringArray(value.fewShotNotes),
    alternativeAction: safeStringOrNull(value.alternativeAction),
    llmRefineRequested: safeBoolean(value.llmRefineRequested),
    llmRefineApplied: safeBoolean(value.llmRefineApplied),
    llmRefineProvider: safeStringOrNull(value.llmRefineProvider),
    llmRefineNotes: safeStringArray(value.llmRefineNotes),
    llmRefineGuardrailFlags: safeStringArray(value.llmRefineGuardrailFlags),
    llmStatus: llmStatus
      ? {
          mode: safeString(llmStatus.mode, "deterministic"),
          label: safeString(llmStatus.label, "Детерминированный"),
          provider: safeStringOrNull(llmStatus.provider),
          detail: safeStringOrNull(llmStatus.detail),
        }
      : null,
    llmDebug: llmDebug
      ? {
          mode: safeString(llmDebug.mode, "deterministic"),
          baselineMessages: safeStringArray(llmDebug.baselineMessages),
          baselineText: safeStringOrNull(llmDebug.baselineText),
          rawCandidate: safeStringOrNull(llmDebug.rawCandidate),
          decisionReason: decisionReason
            ? {
                source: safeString(decisionReason.source, "unknown"),
                code: safeString(decisionReason.code, "unknown"),
                summary: safeString(decisionReason.summary, ""),
                detail: safeString(decisionReason.detail, ""),
                flags: safeStringArray(decisionReason.flags),
              }
            : null,
        }
      : null,
    variants: rawVariants
      .map((item) => {
        if (!isPlainObject(item)) {
          return null;
        }
        return {
          id: safeString(item.id, "variant"),
          label: safeString(item.label, "Вариант"),
          description: safeString(item.description, ""),
          text: safeString(item.text, ""),
        };
      })
      .filter(
        (
          item,
        ): item is { id: string; label: string; description: string; text: string } =>
          Boolean(item && item.text.trim()),
      ),
  };
}

export function normalizeReplyPreviewPayload(value: unknown): ReplyPreviewPayload | null {
  if (!isPlainObject(value)) {
    return null;
  }

  const actions = isPlainObject(value.actions) ? value.actions : {};

  return {
    kind: safeString(value.kind, "unknown"),
    chatId: safeNumberOrNull(value.chatId),
    chatTitle: safeStringOrNull(value.chatTitle),
    chatReference: safeStringOrNull(value.chatReference),
    errorMessage: safeStringOrNull(value.errorMessage),
    sourceSenderName: safeStringOrNull(value.sourceSenderName),
    sourceMessagePreview: safeStringOrNull(value.sourceMessagePreview),
    suggestion: normalizeReplySuggestion(value.suggestion),
    actions: {
      copy: safeBoolean(actions.copy),
      refresh: safeBoolean(actions.refresh, true),
      pasteToTelegram: safeBoolean(actions.pasteToTelegram),
      send: safeBoolean(actions.send),
      markSent: safeBoolean(actions.markSent),
      variants: safeRecord<boolean>(actions.variants),
      disabledReason: safeStringOrNull(actions.disabledReason),
    },
  };
}

export function normalizeAutopilotPayload(value: unknown): AutopilotPayload | null {
  if (!isPlainObject(value)) {
    return null;
  }
  const decision = isPlainObject(value.decision) ? value.decision : {};
  const cooldown = isPlainObject(value.cooldown) ? value.cooldown : {};
  const pendingDraft = isPlainObject(value.pendingDraft) ? value.pendingDraft : null;
  const journal = Array.isArray(value.journal)
    ? value.journal.filter((item): item is Record<string, unknown> => isPlainObject(item))
    : [];
  return {
    masterEnabled: safeBoolean(value.masterEnabled),
    allowChannels: safeBoolean(value.allowChannels),
    mode: safeString(value.mode, "off"),
    trusted: safeBoolean(value.trusted),
    writeReady: safeBoolean(value.writeReady),
    decision: {
      mode: safeString(decision.mode, "off"),
      action: safeString(decision.action, "none"),
      allowed: safeBoolean(decision.allowed),
      reason: safeString(decision.reason, "Нет решения автопилота."),
      confidence: safeNumberOrNull(decision.confidence),
      trigger: safeStringOrNull(decision.trigger),
      sourceMessageId: safeNumberOrNull(decision.sourceMessageId),
      replyText: safeStringOrNull(decision.replyText),
      pendingDraftStatus: safeStringOrNull(decision.pendingDraftStatus),
    },
    pendingDraft: pendingDraft
      ? {
          text: safeStringOrNull(pendingDraft.text) ?? undefined,
          mode: safeStringOrNull(pendingDraft.mode) ?? undefined,
          status: safeStringOrNull(pendingDraft.status) ?? undefined,
          created_at: safeStringOrNull(pendingDraft.created_at) ?? undefined,
          source_message_id: safeNumberOrNull(pendingDraft.source_message_id) ?? undefined,
          confidence: safeNumberOrNull(pendingDraft.confidence) ?? undefined,
          trigger: safeStringOrNull(pendingDraft.trigger) ?? undefined,
          focus_label: safeStringOrNull(pendingDraft.focus_label) ?? undefined,
          source_message_preview: safeStringOrNull(pendingDraft.source_message_preview) ?? undefined,
          reply_opportunity_reason: safeStringOrNull(pendingDraft.reply_opportunity_reason) ?? undefined,
        }
      : null,
    lastSentAt: safeStringOrNull(value.lastSentAt),
    lastSentSourceMessageId: safeNumberOrNull(value.lastSentSourceMessageId),
    cooldown: {
      active: safeBoolean(cooldown.active),
      remainingSeconds: safeNumberOrNull(cooldown.remainingSeconds) ?? 0,
      until: safeStringOrNull(cooldown.until),
    },
    journal: journal.map((item) => ({
      timestamp: safeStringOrNull(item.timestamp) ?? undefined,
      action: safeStringOrNull(item.action) ?? undefined,
      mode: safeStringOrNull(item.mode) ?? undefined,
      status: safeStringOrNull(item.status) ?? undefined,
      actor: safeStringOrNull(item.actor) ?? undefined,
      automatic: typeof item.automatic === "boolean" ? item.automatic : undefined,
      message: safeStringOrNull(item.message) ?? undefined,
      reason: safeStringOrNull(item.reason),
      confidence: safeNumberOrNull(item.confidence),
      trigger: safeStringOrNull(item.trigger),
      chat_id: safeNumberOrNull(item.chat_id),
      source_message_id: safeNumberOrNull(item.source_message_id),
      sent_message_id: safeNumberOrNull(item.sent_message_id),
      text_preview: safeStringOrNull(item.text_preview),
    })),
  };
}

export function normalizeChatFreshnessPayload(value: unknown): ChatFreshnessPayload {
  if (!isPlainObject(value)) {
    return {
      mode: "local",
      label: "Статус недоступен",
      detail: "Bridge не вернул понятный статус свежести.",
      isStale: false,
      fullaccessReady: false,
      canManualSync: false,
      lastSyncAt: null,
      reference: null,
      createdCount: 0,
      updatedCount: 0,
      skippedCount: 0,
      syncTrigger: null,
      updatedNow: false,
      syncError: null,
    };
  }

  return {
    mode: safeString(value.mode, "local"),
    label: safeString(value.label, "Статус недоступен"),
    detail: safeString(value.detail, "Статус свежести недоступен."),
    isStale: safeBoolean(value.isStale),
    fullaccessReady: safeBoolean(value.fullaccessReady),
    canManualSync: safeBoolean(value.canManualSync),
    lastSyncAt: safeStringOrNull(value.lastSyncAt),
    reference: safeStringOrNull(value.reference),
    createdCount: safeNumberOrNull(value.createdCount) ?? 0,
    updatedCount: safeNumberOrNull(value.updatedCount) ?? 0,
    skippedCount: safeNumberOrNull(value.skippedCount) ?? 0,
    syncTrigger: safeStringOrNull(value.syncTrigger),
    updatedNow: safeBoolean(value.updatedNow),
    syncError: safeStringOrNull(value.syncError),
  };
}
