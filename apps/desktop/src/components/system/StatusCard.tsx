import { Badge } from "@/components/ui/badge";
import { getStatusDotClasses, getStatusToneClasses, getStatusToneLabel } from "@/lib/format";
import type { StatusCardItem } from "@/lib/types";
import { cn } from "@/lib/utils";

interface StatusCardProps {
  item: StatusCardItem;
}

export function StatusCard({ item }: StatusCardProps) {
  return (
    <div className="rounded-[24px] border border-white/7 bg-white/[0.035] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-slate-100">{item.label}</div>
        <Badge
          variant="outline"
          className={cn("gap-2 border-0 ring-1", getStatusToneClasses(item.status))}
        >
          <span className={cn("size-2 rounded-full", getStatusDotClasses(item.status))} />
          {getStatusToneLabel(item.status)}
        </Badge>
      </div>
      <div className="text-xl font-semibold tracking-tight text-white">{item.value}</div>
      <div className="mt-2 text-sm leading-5 text-slate-400">{item.detail}</div>
    </div>
  );
}
