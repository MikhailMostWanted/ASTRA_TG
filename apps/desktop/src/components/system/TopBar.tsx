import { FolderKanban, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDateTime } from "@/lib/format";
import type { HealthPayload } from "@/lib/types";

interface TopBarProps {
  title: string;
  description: string;
  health?: HealthPayload;
  repositoryRoot?: string;
  onRefreshAll: () => void;
  menuTrigger?: React.ReactNode;
}

export function TopBar({
  title,
  description,
  health,
  repositoryRoot,
  onRefreshAll,
  menuTrigger,
}: TopBarProps) {
  return (
    <header className="z-20 flex shrink-0 flex-wrap items-start justify-between gap-4 border-b border-white/6 bg-[rgba(4,8,17,0.92)] px-4 py-4 backdrop-blur-2xl sm:px-5">
      <div className="flex min-w-0 items-start gap-3">
        {menuTrigger}
        <div className="flex min-w-0 flex-col gap-1">
          <div className="text-[11px] uppercase tracking-[0.28em] text-slate-500">Astra Control</div>
          <div className="truncate text-2xl font-semibold tracking-tight text-white">{title}</div>
          <div className="max-w-3xl text-sm leading-6 text-slate-400">{description}</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-0 bg-white/6 text-slate-200 ring-1 ring-white/10">
          {health?.ok ? "Bridge подключён" : "Bridge недоступен"}
        </Badge>
        <Badge variant="outline" className="border-0 bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/10">
          {formatDateTime(new Date().toISOString())}
        </Badge>
        {repositoryRoot ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="max-w-[220px] truncate border-0 bg-white/6 text-slate-300 ring-1 ring-white/10">
                <FolderKanban data-icon="inline-start" />
                {repositoryRoot}
              </Badge>
            </TooltipTrigger>
            <TooltipContent side="bottom">{repositoryRoot}</TooltipContent>
          </Tooltip>
        ) : null}
        <Button variant="outline" className="border-white/8 bg-black/18 text-slate-100" onClick={onRefreshAll}>
          <RefreshCw data-icon="inline-start" />
          Обновить всё
        </Button>
      </div>
    </header>
  );
}
