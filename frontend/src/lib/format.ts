import type { DealLabel } from "./types";

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

/** ₹1,23,456 with Indian digit grouping. */
export function formatINR(value: number | null | undefined): string {
  return value == null ? "—" : inr.format(value);
}

export function formatPct(value: number | null | undefined, digits = 0): string {
  return value == null ? "—" : `${value.toFixed(digits)}%`;
}

export function platformName(platform: string | null | undefined): string {
  if (!platform) return "—";
  return ({ amazon: "Amazon", flipkart: "Flipkart" } as Record<string, string>)[platform] ?? platform.charAt(0).toUpperCase() + platform.slice(1);
}

/** "12 minutes ago" – always relative to the supplied reference time. */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const units: [number, string][] = [[86400, "day"], [3600, "hour"], [60, "minute"]];
  for (const [size, name] of units) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size);
      return `${n} ${name}${n === 1 ? "" : "s"} ago`;
    }
  }
  return "just now";
}

export function formatDate(iso: string, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }): string {
  return new Date(iso).toLocaleDateString("en-IN", opts);
}

export const CATEGORY_TITLES: Record<string, string> = {
  mobiles: "Mobile deals", laptops: "Laptop deals", tv: "TV deals",
  electronics: "Electronics deals", "home-appliances": "Home appliance deals",
};

export function categoryTitle(slug: string): string {
  return CATEGORY_TITLES[slug] ?? `${slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} deals`;
}

export const TIER: Record<DealLabel, { text: string; bg: string; fg: string }> = {
  exceptional: { text: "Exceptional deal", bg: "var(--tier-exceptional-bg)", fg: "var(--tier-exceptional-fg)" },
  great: { text: "Great deal", bg: "var(--tier-great-bg)", fg: "var(--tier-great-fg)" },
  good: { text: "Good deal", bg: "var(--tier-good-bg)", fg: "var(--tier-good-fg)" },
  average: { text: "Average", bg: "var(--tier-average-bg)", fg: "var(--tier-average-fg)" },
  poor: { text: "Not a good deal", bg: "var(--tier-poor-bg)", fg: "var(--tier-poor-fg)" },
  insufficient_data: { text: "Not enough history yet", bg: "var(--tier-none-bg)", fg: "var(--tier-none-fg)" },
};
