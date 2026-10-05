"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** A disclosure that is collapsed on phones and always open on large screens. */
export function FilterShell({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const sync = () => { if (ref.current) ref.current.open = mq.matches; };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return <details ref={ref}>{children}</details>;
}
