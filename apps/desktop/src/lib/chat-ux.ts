import type {
  AutopilotPayload,
  ChatFreshnessPayload,
  ChatRosterStatePayload,
  LiveStatusPayload,
  WorkspaceStatusPayload,
} from "@/lib/types";

export type UiTone = "success" | "warning" | "danger" | "info" | "muted";

export interface UiStatusCopy {
  label: string;
  detail: string;
  tone: UiTone;
}

export function buildFreshnessCopy(
  freshness?: ChatFreshnessPayload | null,
  live?: LiveStatusPayload | null,
  status?: WorkspaceStatusPayload | null,
): UiStatusCopy {
  if (live?.degraded || live?.lastError || freshness?.syncError || status?.syncError) {
    return {
      label: "связь с Telegram нестабильна",
      detail: live?.lastError || freshness?.syncError || status?.syncError || "Последнее обновление прошло с ошибкой.",
      tone: "danger",
    };
  }

  if (live?.paused) {
    return {
      label: "live на паузе",
      detail: "Автообновление остановлено. Можно обновить чат вручную или снова включить live.",
      tone: "warning",
    };
  }

  if (live?.syncing) {
    return {
      label: "ищу новые сообщения",
      detail: "Astra проверяет хвост чата и не должна сбивать текущий просмотр.",
      tone: "info",
    };
  }

  const newCount = live?.meaningfulMessageCount || live?.newMessageCount || 0;
  if (newCount > 0) {
    return {
      label: "есть новые",
      detail: `${newCount} новых сигналов попали в рабочий контекст.`,
      tone: "success",
    };
  }

  if (freshness?.updatedNow || status?.updatedNow) {
    return {
      label: "обновлено только что",
      detail: "Лента и панель ответа смотрят в один свежий снимок.",
      tone: "success",
    };
  }

  if (freshness?.isStale) {
    return {
      label: "контекст устаревает",
      detail: freshness.detail || "Лучше обновить чат перед отправкой.",
      tone: "warning",
    };
  }

  return {
    label: freshness?.label || "контекст готов",
    detail: freshness?.detail || "Свежесть проверяется при каждом обновлении чата.",
    tone: "muted",
  };
}

export function buildLiveCopy(live?: LiveStatusPayload | null): UiStatusCopy {
  if (!live) {
    return {
      label: "live ждёт данных",
      detail: "Статус живого обновления появится после загрузки рабочего контекста.",
      tone: "muted",
    };
  }

  if (live.paused) {
    return {
      label: "live на паузе",
      detail: "Автообновление этого чата остановлено.",
      tone: "warning",
    };
  }

  if (live.degraded || live.lastError) {
    return {
      label: "связь с Telegram нестабильна",
      detail: live.lastError || "Live временно работает с ошибками.",
      tone: "danger",
    };
  }

  if (live.pendingConfirmation) {
    return {
      label: "ждёт подтверждение",
      detail: "Полуавтомат подготовил текст, но отправка требует явного подтверждения.",
      tone: "warning",
    };
  }

  if (live.syncing) {
    return {
      label: "ищу новые сообщения",
      detail: "Проверяю, появился ли новый смысловой сигнал.",
      tone: "info",
    };
  }

  const newCount = live.meaningfulMessageCount || live.newMessageCount || live.changedItemCount || 0;
  if (newCount > 0) {
    return {
      label: "есть новые",
      detail: `${newCount} новых изменений в live-контуре.`,
      tone: "success",
    };
  }

  return {
    label: "обновлено только что",
    detail: "Live держит чат и ответную панель на одном снимке.",
    tone: "success",
  };
}

export function buildWorkspaceCopy(status?: WorkspaceStatusPayload | null): UiStatusCopy {
  if (!status) {
    return {
      label: "контекст не загружен",
      detail: "Выбери чат или обнови список, чтобы собрать рабочий снимок.",
      tone: "muted",
    };
  }

  if (status.degraded) {
    return {
      label: "связь с Telegram нестабильна",
      detail: status.degradedReason || status.lastError || "Обнови чат, чтобы получить свежий снимок.",
      tone: "warning",
    };
  }

  if (!status.availability.workspaceAvailable || (!status.availability.runtimeReadable && !status.availability.legacyWorkspaceAvailable)) {
    return {
      label: "чат пока недоступен",
      detail: "Astra видит чат в списке, но историю сейчас прочитать не может.",
      tone: "danger",
    };
  }

  if (status.effectiveBackend === "new" || status.source === "new") {
    return {
      label: "Telegram подключён",
      detail: "История читается напрямую из основного runtime.",
      tone: "success",
    };
  }

  return {
    label: "локальный контекст",
    detail: "Astra использует сохранённую локальную историю.",
    tone: "muted",
  };
}

export function buildRosterCopy(roster?: ChatRosterStatePayload | null, live?: LiveStatusPayload | null): UiStatusCopy {
  if (live?.degraded || roster?.degraded) {
    return {
      label: roster?.requestedBackend === "new" ? "runtime недоступен" : "связь с Telegram нестабильна",
      detail: roster?.degradedReason || live?.lastError || "Список чатов обновляется с ошибками.",
      tone: roster?.requestedBackend === "new" ? "danger" : "warning",
    };
  }

  if (live?.syncing) {
    return {
      label: "ищу новые сообщения",
      detail: "Обновляю список чатов.",
      tone: "info",
    };
  }

  const changed = live?.changedItemCount || 0;
  if (changed > 0) {
    return {
      label: "есть новые",
      detail: `${changed} чатов изменились после последней проверки.`,
      tone: "success",
    };
  }

  if (roster?.source === "new") {
    return {
      label: "Telegram подключён",
      detail: "Список чатов приходит из основного runtime.",
      tone: "success",
    };
  }

  return {
    label: "список готов",
    detail: "Чаты можно фильтровать и открывать без ручной синхронизации.",
    tone: "muted",
  };
}

export function formatAutopilotMode(mode: string | null | undefined): string {
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

export function autopilotModeTone(mode: string | null | undefined): UiTone {
  if (mode === "autopilot") {
    return "danger";
  }
  if (mode === "confirm" || mode === "semi_auto") {
    return "warning";
  }
  if (mode === "draft") {
    return "info";
  }
  return "muted";
}

export function buildAutopilotCopy(autopilot?: AutopilotPayload | null): UiStatusCopy {
  if (!autopilot) {
    return {
      label: "автопилот недоступен",
      detail: "Bridge пока не вернул состояние reply execution.",
      tone: "muted",
    };
  }

  if (autopilot.emergencyStop) {
    return {
      label: "экстренный стоп активен",
      detail: "Автоматические действия остановлены глобально.",
      tone: "danger",
    };
  }

  if (autopilot.pendingDraft?.status === "awaiting_confirmation") {
    return {
      label: "ждёт подтверждение",
      detail: "Полуавтомат подготовил текст и ждёт явного подтверждения.",
      tone: "warning",
    };
  }

  if (autopilot.autopilotPaused) {
    return {
      label: "автопилот на паузе",
      detail: "Astra может готовить подсказки, но автоматические действия не выполняются.",
      tone: "warning",
    };
  }

  const mode = autopilot.effectiveMode || autopilot.mode || autopilot.globalMode || "off";
  const blockedReason = autopilot.decision?.reason || autopilot.state?.reason || "";
  return {
    label: formatAutopilotMode(mode),
    detail: blockedReason || "Режим безопасно применён к текущему чату.",
    tone: autopilotModeTone(mode),
  };
}

export function toneBadgeClasses(tone: UiTone): string {
  switch (tone) {
    case "success":
      return "bg-emerald-300/12 text-emerald-100 ring-emerald-300/15";
    case "warning":
      return "bg-amber-300/12 text-amber-100 ring-amber-300/15";
    case "danger":
      return "bg-rose-400/12 text-rose-100 ring-rose-300/15";
    case "info":
      return "bg-cyan-300/12 text-cyan-100 ring-cyan-300/15";
    default:
      return "bg-white/7 text-slate-200 ring-white/10";
  }
}

export function tonePanelClasses(tone: UiTone): string {
  switch (tone) {
    case "success":
      return "border-emerald-300/14 bg-emerald-300/8";
    case "warning":
      return "border-amber-300/16 bg-amber-300/8";
    case "danger":
      return "border-rose-300/16 bg-rose-400/8";
    case "info":
      return "border-cyan-300/14 bg-cyan-300/8";
    default:
      return "border-white/8 bg-white/[0.03]";
  }
}

export function compactReason(value: string | null | undefined, fallback = "Причина не указана."): string {
  const cleaned = value?.replace(/\s+/g, " ").trim();
  if (!cleaned) {
    return fallback;
  }
  return cleaned.length > 180 ? `${cleaned.slice(0, 177).trim()}...` : cleaned;
}
