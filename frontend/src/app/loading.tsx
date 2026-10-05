import { GridSkeleton } from "@/components/States";

export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="skeleton h-10 w-72" aria-hidden="true" />
      <GridSkeleton count={8} />
    </div>
  );
}
