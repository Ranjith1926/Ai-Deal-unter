import { EmptyState } from "@/components/States";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl py-10">
      <EmptyState title="We couldn't find that page" action={{ href: "/deals", label: "Browse deals" }}>
        The product or page may have been removed, or the link is mistyped.
      </EmptyState>
    </div>
  );
}
