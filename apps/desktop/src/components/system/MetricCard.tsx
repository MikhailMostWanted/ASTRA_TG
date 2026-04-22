import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string;
  note: string;
  icon: LucideIcon;
  className?: string;
}

export function MetricCard({
  label,
  value,
  note,
  icon: Icon,
  className,
}: MetricCardProps) {
  return (
    <div
      className={cn(
        "rounded-[22px] border border-white/7 bg-black/15 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]",
        className,
      )}
    >
      <div className="mb-5 flex items-center justify-between gap-3">
        <div className="text-xs uppercase tracking-[0.22em] text-slate-500">{label}</div>
        <div className="flex size-9 items-center justify-center rounded-2xl bg-cyan-400/10 text-cyan-100">
          <Icon />
        </div>
      </div>
      <div className="text-2xl font-semibold tracking-tight text-white">{value}</div>
      <div className="mt-2 text-sm leading-5 text-slate-400">{note}</div>
    </div>
  );
}
