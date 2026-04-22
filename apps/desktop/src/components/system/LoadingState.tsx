import { Skeleton } from "@/components/ui/skeleton";

export function LoadingState() {
  return (
    <div className="space-y-4 rounded-[24px] border border-white/7 bg-white/[0.03] p-5">
      <Skeleton className="h-5 w-40 rounded-full bg-white/10" />
      <Skeleton className="h-16 rounded-[18px] bg-white/8" />
      <Skeleton className="h-16 rounded-[18px] bg-white/8" />
      <Skeleton className="h-16 rounded-[18px] bg-white/8" />
    </div>
  );
}
