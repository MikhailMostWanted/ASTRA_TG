import { startTransition } from "react";
import { Bot, Sparkles } from "lucide-react";
import { motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { formatDateTime } from "@/lib/format";
import type { HealthPayload, ScreenId } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { NavigationItem } from "@/lib/navigation";

interface SidebarProps {
  items: NavigationItem[];
  activeScreen: ScreenId;
  onSelectScreen: (screen: ScreenId) => void;
  health?: HealthPayload;
  repositoryRoot?: string;
  onClose?: () => void;
}

export function Sidebar({
  items,
  activeScreen,
  onSelectScreen,
  health,
  repositoryRoot,
  onClose,
}: SidebarProps) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[30px] border border-white/8 bg-black/24 px-4 py-4 backdrop-blur-2xl">
      <div className="flex items-center justify-between gap-3 px-2">
        <div className="flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-[18px] bg-gradient-to-br from-cyan-300/30 via-cyan-400/12 to-amber-200/15 text-cyan-100 shadow-[0_0_40px_rgba(34,211,238,0.08)]">
            <Bot />
          </div>
          <div className="flex flex-col gap-1">
            <div className="text-sm uppercase tracking-[0.24em] text-slate-500">Astra AFT</div>
            <div className="text-lg font-semibold tracking-tight text-white">Desktop Console</div>
          </div>
        </div>
        <Badge
          variant="outline"
          className={cn(
            "border-0 bg-emerald-400/12 text-emerald-100 ring-1 ring-emerald-300/15",
            !health?.ok && "bg-amber-300/10 text-amber-100 ring-amber-300/15",
          )}
        >
          <Sparkles data-icon="inline-start" />
          {health?.ok ? "bridge online" : "bridge offline"}
        </Badge>
      </div>

      <Separator className="my-4 bg-white/8" />

      <ScrollArea className="min-h-0 flex-1">
        <nav className="flex flex-col gap-1.5 pr-2">
          {items.map((item) => {
            const isActive = item.id === activeScreen;

            return (
              <button
                key={item.id}
                type="button"
                className={cn(
                  "group relative overflow-hidden rounded-[22px] px-3 py-3 text-left transition-all active:translate-y-px",
                  isActive
                    ? "text-white"
                    : "text-slate-300 hover:bg-white/[0.045] hover:text-white active:bg-white/[0.08]",
                )}
                onClick={() => {
                  startTransition(() => onSelectScreen(item.id));
                  onClose?.();
                }}
              >
                {isActive ? (
                  <motion.div
                    layoutId="astra-sidebar-active"
                    className="absolute inset-0 rounded-[22px] border border-cyan-300/10 bg-gradient-to-br from-cyan-300/12 via-white/[0.045] to-white/[0.02] shadow-[0_10px_35px_rgba(17,24,39,0.25)]"
                  />
                ) : null}
                <div className="relative flex items-start gap-3">
                  <div
                    className={cn(
                      "mt-0.5 flex size-10 items-center justify-center rounded-2xl border border-white/8 bg-white/[0.03]",
                      isActive && "border-cyan-300/12 bg-cyan-400/10 text-cyan-100",
                    )}
                  >
                    <item.icon />
                  </div>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="text-sm font-medium tracking-tight">{item.label}</div>
                    <div className="text-xs leading-5 text-slate-400">{item.description}</div>
                  </div>
                </div>
              </button>
            );
          })}
        </nav>
      </ScrollArea>

      <Separator className="my-4 bg-white/8" />

      <div className="flex flex-col gap-3 rounded-[22px] border border-white/7 bg-white/[0.03] p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-medium text-white">Локальный контур</div>
          <Badge variant="outline" className="border-0 bg-white/8 text-slate-200 ring-1 ring-white/10">
            v{health?.version || "0.1"}
          </Badge>
        </div>
        <div className="flex flex-col gap-1 text-xs leading-5 text-slate-400">
          <div>Репозиторий: {repositoryRoot || "—"}</div>
          <div>Обновлено: {formatDateTime(new Date().toISOString())}</div>
          <div>API: {health?.name || "astra-desktop-api"}</div>
        </div>
      </div>
    </aside>
  );
}
