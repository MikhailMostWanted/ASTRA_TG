import type { ReactNode } from "react";
import { CheckCircle2 } from "lucide-react";

interface SuccessStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function SuccessState({ title, description, action }: SuccessStateProps) {
  return (
    <div className="flex min-h-40 flex-col justify-center gap-4 rounded-[24px] border border-emerald-300/12 bg-emerald-400/6 px-5 py-6">
      <div className="flex items-center gap-3 text-emerald-100">
        <div className="flex size-10 items-center justify-center rounded-full bg-emerald-300/12">
          <CheckCircle2 />
        </div>
        <div className="text-base font-medium">{title}</div>
      </div>
      <div className="max-w-2xl text-sm leading-6 text-emerald-50/80">{description}</div>
      {action}
    </div>
  );
}
