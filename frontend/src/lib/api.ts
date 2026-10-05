import "server-only";
import { cookies, headers as requestHeaders } from "next/headers";
import { forwardedFor } from "./clientip";
import type { Envelope, Meta } from "./types";

const BASE = process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const ACCESS_COOKIE = "dh_at";
export const REFRESH_COOKIE = "dh_rt";

export class ApiError extends Error {
  constructor(public status: number, message: string, public errors: string[] = []) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;
interface Options { query?: Query; revalidate?: number; auth?: boolean }
export interface ApiResult<T> { data: T; meta?: Meta; message: string | null }

function buildUrl(path: string, query?: Query): string {
  const url = new URL(path, BASE);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  return url.toString();
}

/** GET from the backend. Public data is cached briefly; authenticated data never is. */
export async function api<T>(path: string, { query, revalidate = 60, auth = false }: Options = {}): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (auth) {
    const token = (await cookies()).get(ACCESS_COOKIE)?.value;
    if (!token) throw new ApiError(401, "Authentication required");
    headers.Authorization = `Bearer ${token}`;
    Object.assign(headers, forwardedFor(await requestHeaders()));
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), { headers, ...(auth ? { cache: "no-store" as const } : { next: { revalidate } }) });
  } catch {
    throw new ApiError(503, "The deals service is unreachable right now");
  }
  const body = (await res.json().catch(() => null)) as Envelope<T> | null;
  if (!res.ok || !body?.success) {
    throw new ApiError(res.status, body?.message ?? `Request failed (${res.status})`, body?.errors ?? []);
  }
  return { data: body.data as T, meta: body.meta, message: body.message };
}

/** Like `api`, but returns null instead of throwing, so one failing section cannot break a page. */
export async function tryApi<T>(path: string, options?: Options): Promise<ApiResult<T> | null> {
  try {
    return await api<T>(path, options);
  } catch {
    return null;
  }
}
