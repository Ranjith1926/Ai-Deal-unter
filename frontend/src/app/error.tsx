"use client";

import { RotateCcw } from "lucide-react";
import { ErrorState } from "@/components/States";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="mx-auto max-w-xl space-y-4 py-10">
      <ErrorState title="Something went wrong" />
      <button type="button" onClick={reset} className="btn btn-primary"><RotateCcw size={18} aria-hidden="true" /> Try again</button>
    </div>
  );
}
