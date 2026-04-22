import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BookHeart,
  DatabaseZap,
  LayoutDashboard,
  ListTodo,
  MessageSquareText,
  ShieldEllipsis,
  Waypoints,
} from "lucide-react";

import type { ScreenId } from "@/lib/types";

export interface NavigationItem {
  id: ScreenId;
  label: string;
  description: string;
  icon: LucideIcon;
}

export const navigationItems: NavigationItem[] = [
  {
    id: "dashboard",
    label: "Сводка",
    description: "Состояние Astra, быстрые действия и свежие сигналы.",
    icon: LayoutDashboard,
  },
  {
    id: "chats",
    label: "Чаты",
    description: "Основной рабочий экран с контекстом и reply preview.",
    icon: MessageSquareText,
  },
  {
    id: "sources",
    label: "Источники",
    description: "Локальные источники, sync и ручное добавление.",
    icon: Waypoints,
  },
  {
    id: "fullaccess",
    label: "Full-access",
    description: "Локальный read-only вход и ручная синхронизация истории.",
    icon: ShieldEllipsis,
  },
  {
    id: "memory",
    label: "Память",
    description: "Карточки памяти по чатам и людям.",
    icon: BookHeart,
  },
  {
    id: "digest",
    label: "Дайджест",
    description: "Запуски digest и текущая точка доставки.",
    icon: Activity,
  },
  {
    id: "reminders",
    label: "Напоминания",
    description: "Задачи, кандидаты и delivery pipeline.",
    icon: ListTodo,
  },
  {
    id: "logs",
    label: "Логи и Ops",
    description: "Doctor, последние логи и операции обслуживания.",
    icon: DatabaseZap,
  },
];
