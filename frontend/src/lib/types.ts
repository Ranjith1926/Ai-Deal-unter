// Mirrors the backend response schemas (backend/app/schemas).

export interface Meta { page: number; page_size: number; total: number; pages: number }
export interface Envelope<T> { success: boolean; data: T | null; message: string | null; errors: string[]; meta?: Meta }

export type DealLabel = "exceptional" | "great" | "good" | "average" | "poor" | "insufficient_data";

export interface PlatformPrice {
  platform: string; price: number | null; mrp: number | null; availability: string; seller: string | null;
  buy_url: string | null; is_affiliate_link: boolean; updated_at: string | null; is_stale: boolean;
  rating: number | null; review_count: number | null;
}

export interface ProductCard {
  id: number; name: string; brand: string; category: string | null; image_url: string | null;
  current_price: number | null; previous_price: number | null; typical_price: number | null;
  historical_low: number | null; price_drop_pct: number | null; advertised_discount_pct: number | null;
  deal_score: number | null; value_score: number | null; deal_label: DealLabel; deal_label_text: string;
  note: string | null; score_calculated_at: string | null;
  best_platform: string | null; platforms: PlatformPrice[]; rating: number | null; review_count: number | null;
  buy_url: string | null; is_affiliate_link: boolean; price_updated_at: string | null; is_stale: boolean;
}

export interface Explanation { code: string; text: string; positive: boolean }
export interface Offer { platform: string; offer_type: string; description: string; discount_amount: number | null; valid_until: string | null }
export interface Discount { advertised_pct: number | null; typical_price: number | null; real_saving: number | null; real_saving_pct: number | null; is_misleading: boolean | null }
export interface Factor { key: string; weight: number; score: number | null; detail: Record<string, unknown> }

export interface ProductDetail extends ProductCard {
  description: string | null; model_number: string | null; variant_key: string;
  specifications: Record<string, string>; explanation: Explanation[]; discount: Discount | null;
  offers: Offer[]; stats: Record<string, number | string | boolean | null> | null;
  score_breakdown: { deal?: { factors?: Factor[]; confidence?: number; adjustments?: string[] } | null; value?: { factors?: Factor[]; confidence?: number } | null } | null;
}

export interface DealEvent { event_type: string; detected_at: string; price: number | null; previous_price: number | null; detail: Record<string, unknown> }
export interface DealWithEvent { product: ProductCard; event: DealEvent }

export interface PricePoint { t: string; price: number | null; low: number | null; high: number | null; available: boolean }
export interface PriceHistory {
  product_id: number; days: number; resolution: "raw" | "daily"; series: Record<string, PricePoint[]>;
  stats: Record<string, number | string | boolean | null> | null; has_sufficient_history: boolean; message: string | null;
}

export interface PlatformComparison {
  platform: string; price: number | null; mrp: number | null; availability: string; seller: string | null;
  shipping: string | null; warranty: string | null; bank_offers: Offer[]; exchange_offers: Offer[]; other_offers: Offer[];
  price_after_offers: number | null; difference_vs_cheapest: number | null; buy_url: string | null;
  is_affiliate_link: boolean; updated_at: string | null; is_stale: boolean;
  field_status: Record<string, "verified" | "estimated" | "unavailable">;
}
export interface Comparison { product_id: number; product_name: string; platforms: PlatformComparison[]; best_platform: string | null; price_difference: number | null; summary: string }

export interface ProductComparison {
  products: ProductDetail[]; spec_keys: string[]; cheapest_id: number | null;
  best_value_id: number | null; best_deal_id: number | null; summary: string[];
}

export interface AdminProvider {
  name: string; enabled: boolean; mode: "demo" | "live" | "unavailable"; listings: number;
  last_success_at: string | null; last_status: string | null; last_job: string | null; last_error: string | null;
  failures_24h: number; avg_sync_seconds: number | null; health: "healthy" | "attention" | "disabled";
}
export interface AdminStats {
  generated_at: string;
  products: { total: number; active: number; amazon: number; flipkart: number };
  last_24h: { deals: number; price_drops: number; historical_lows: number; failed_jobs: number };
  users: number; alerts: { active: number; total: number };
  average_sync_seconds: number | null; last_successful_sync_at: string | null; providers: AdminProvider[];
}
export interface AdminJob {
  id: number; provider: string; job: string; status: string; records_processed: number; error: string | null;
  started_at: string; completed_at: string | null; duration_seconds: number | null;
}
export interface AdminCategory { id: number; name: string; slug: string; parent_id: number | null; product_count: number }
export interface AdminListing {
  id: number; platform: string; external_id: string; is_active: boolean; price: number | null; availability: string;
  last_seen_at: string | null; match_method: string | null; match_confidence: number | null;
}
export interface AdminProduct {
  id: number; name: string; brand: string; category_id: number | null; category: string | null; is_active: boolean;
  model_number: string | null; created_at: string; listings: AdminListing[];
}
export interface ScoringState {
  customised: boolean; overrides: Record<string, unknown>; updated_at: string | null;
  defaults: ScoringConfigShape; effective: ScoringConfigShape;
}
export interface ScoringConfigShape {
  deal: { weights: Record<string, number>; thresholds: Record<string, number> };
  value: { weights: Record<string, number> };
}

export interface Category { id: number; name: string; slug: string; product_count: number }
export interface Recommendation { rank: number; score: number; product: ProductCard; reasons: string[] }

export interface Alert {
  id: number; product_id: number; product_name: string; target_price: number; platform: string | null;
  is_active: boolean; triggered_at: string | null; created_at: string; current_price: number | null; amount_above_target: number | null;
}
export interface User { id: number; email: string; name: string; is_admin: boolean; notification_preferences: Record<string, unknown>; created_at: string }
export interface NotificationChannels { email: boolean; telegram: boolean; push: boolean; vapid_public_key: string | null; telegram_bot_username: string | null }
export interface InboxItem { id: number; title: string; message: string; is_read: boolean; created_at: string }
export interface Inbox { unread: number; items: InboxItem[] }
export interface SiteMeta { data_mode: "demo" | "live"; providers: { name: string; is_mock: boolean }[] }
