import type { ReplyPreviewPayload, ReplySuggestion, ScreenId } from "@/lib/types";

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
    fewShotFound: safeBoolean(value.fewShotFound),
    fewShotMatchCount: safeNumberOrNull(value.fewShotMatchCount) ?? 0,
    fewShotNotes: safeStringArray(value.fewShotNotes),
    alternativeAction: safeStringOrNull(value.alternativeAction),
    llmRefineRequested: safeBoolean(value.llmRefineRequested),
    llmRefineApplied: safeBoolean(value.llmRefineApplied),
    llmRefineProvider: safeStringOrNull(value.llmRefineProvider),
    llmRefineNotes: safeStringArray(value.llmRefineNotes),
    llmRefineGuardrailFlags: safeStringArray(value.llmRefineGuardrailFlags),
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
      markSent: safeBoolean(actions.markSent),
      variants: safeRecord<boolean>(actions.variants),
      disabledReason: safeStringOrNull(actions.disabledReason),
    },
  };
}
