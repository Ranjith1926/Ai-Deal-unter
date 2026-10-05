import "server-only";
import { cache } from "react";
import { redirect } from "next/navigation";
import { ApiError, api } from "./api";
import type { ProductCard, User } from "./types";

/** The signed-in user, or null. Memoised per request. */
export const getUser = cache(async (): Promise<User | null> => {
  try {
    return (await api<User>("/api/me", { auth: true })).data;
  } catch (e) {
    if (e instanceof ApiError) return null;
    throw e;
  }
});

/** Use at the top of pages that need an account; sends visitors to sign in and back. */
export async function requireUser(next: string): Promise<User> {
  const user = await getUser();
  if (!user) redirect(`/login?next=${encodeURIComponent(next)}`);
  return user;
}

/** Favourite product ids for the signed-in user (empty when signed out). */
export const getFavoriteIds = cache(async (): Promise<Set<number>> => {
  if (!(await getUser())) return new Set();
  try {
    const { data } = await api<ProductCard[]>("/api/me/favorites/products", { auth: true });
    return new Set(data.map((p) => p.id));
  } catch {
    return new Set();
  }
});
