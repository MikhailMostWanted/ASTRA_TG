import type { StatusTone } from "@/lib/types";

const dateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const longDateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "long",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDateTime(value: string | null | undefined, long = false) {
  if (!value) {
    return "Пока нет";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return (long ? longDateTimeFormatter : dateTimeFormatter).format(parsed);
}

export function formatRelativeTime(value: string | null | undefined) {
  if (!value) {
    return "без свежих событий";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  const diffMinutes = Math.round((parsed.getTime() - Date.now()) / 60000);
  const absMinutes = Math.abs(diffMinutes);

  if (absMinutes < 1) {
    return "только что";
  }
  if (absMinutes < 60) {
    return `${absMinutes} мин назад`;
  }

  const absHours = Math.round(absMinutes / 60);
  if (absHours < 24) {
    return `${absHours} ч назад`;
  }

  const absDays = Math.round(absHours / 24);
  return `${absDays} дн назад`;
}

export function formatConfidence(value: number | null | undefined) {
  if (value == null) {
    return "без оценки";
  }
  return `${Math.round(value * 100)}%`;
}

export function formatCompactNumber(value: number) {
  return new Intl.NumberFormat("ru-RU").format(value);
}

export function getStatusToneLabel(tone: StatusTone) {
  switch (tone) {
    case "online":
    case "success":
      return "норма";
    case "warning":
      return "внимание";
    case "danger":
      return "ошибка";
    case "offline":
      return "offline";
    default:
      return "спокойно";
  }
}

export function getStatusToneClasses(tone: StatusTone) {
  switch (tone) {
    case "online":
    case "success":
      return "bg-emerald-400/20 text-emerald-200 ring-emerald-400/20";
    case "warning":
      return "bg-amber-400/20 text-amber-100 ring-amber-400/20";
    case "danger":
      return "bg-rose-500/20 text-rose-100 ring-rose-400/20";
    case "offline":
      return "bg-white/8 text-slate-200 ring-white/10";
    default:
      return "bg-cyan-400/16 text-cyan-100 ring-cyan-300/15";
  }
}

export function getStatusDotClasses(tone: StatusTone) {
  switch (tone) {
    case "online":
    case "success":
      return "bg-emerald-300";
    case "warning":
      return "bg-amber-300";
    case "danger":
      return "bg-rose-300";
    case "offline":
      return "bg-slate-400";
    default:
      return "bg-cyan-300";
  }
}

export function initials(value: string | null | undefined) {
  if (!value) {
    return "AS";
  }
  return value
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function stringifyUnknown(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key}: ${stringifyUnknown(item)}`)
      .join(", ");
  }
  return "—";
}
