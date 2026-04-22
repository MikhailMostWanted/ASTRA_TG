import type { ReactNode } from "react";
import { TriangleAlert } from "lucide-react";

interface WarningStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function WarningState({ title, description, action }: WarningStateProps) {
  return (
    <div className="flex min-h-44 flex-col justify-center gap-4 rounded-[24px] border border-amber-300/12 bg-amber-400/6 px-5 py-6">
      <div className="flex items-center gap-3 text-amber-100">
        <div className="flex size-10 items-center justify-center rounded-full bg-amber-300/12">
          <TriangleAlert />
        </div>
        <div className="text-base font-medium">{title}</div>
      </div>
      <div className="max-w-2xl text-sm leading-6 text-amber-50/80">{description}</div>
      {action}
    </div>
  );
}
