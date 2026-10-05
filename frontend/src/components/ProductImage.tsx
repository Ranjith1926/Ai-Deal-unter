import Image from "next/image";
import { Headphones, Laptop, Package, Smartphone, Tv, WashingMachine, type LucideIcon } from "lucide-react";

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  mobiles: Smartphone, laptops: Laptop, tv: Tv, electronics: Headphones, "home-appliances": WashingMachine,
};

/**
 * Real image when the marketplace supplied one; otherwise a neutral category tile. Never a
 * made-up product photo.
 */
export function ProductImage({ src, name, brand, category, className = "h-36" }: {
  src: string | null; name: string; brand: string; category: string | null; className?: string;
}) {
  if (src) {
    return (
      <div className={`relative w-full overflow-hidden rounded-xl bg-white ${className}`}>
        <Image src={src} alt={name} fill sizes="(min-width: 1024px) 25vw, 50vw" className="object-contain p-2" />
      </div>
    );
  }
  const Icon = (category && CATEGORY_ICONS[category]) || Package;
  return (
    <div role="img" aria-label={`${brand} ${name}`} className={`flex w-full flex-col items-center justify-center gap-1 rounded-xl bg-surface-2 text-muted ${className}`}>
      <Icon size={40} strokeWidth={1.5} aria-hidden="true" />
      <span className="font-display text-sm font-bold text-fg">{brand}</span>
    </div>
  );
}
