import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex min-h-56 flex-col items-center justify-center gap-4 rounded-[24px] border border-dashed border-white/10 bg-black/10 px-6 py-10 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-white/6 text-slate-200">
        <Inbox />
      </div>
      <div className="space-y-1">
        <div className="text-base font-medium text-white">{title}</div>
        <div className="max-w-md text-sm leading-6 text-slate-400">{description}</div>
      </div>
      {action}
    </div>
  );
}
