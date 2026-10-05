import "server-only";
import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "./api";

export const BACKEND = process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const REFRESH_DAYS = 30;

export function cookieBase() {
  return { httpOnly: true, sameSite: "lax" as const, secure: process.env.COOKIE_SECURE === "true", path: "/" };
}

export function setAuthCookies(res: NextResponse, t: { access_token: string; refresh_token: string; expires_in: number }) {
  res.cookies.set(ACCESS_COOKIE, t.access_token, { ...cookieBase(), maxAge: t.expires_in });
  res.cookies.set(REFRESH_COOKIE, t.refresh_token, { ...cookieBase(), maxAge: REFRESH_DAYS * 86400 });
}

export function clearAuthCookies(res: NextResponse) {
  res.cookies.set(ACCESS_COOKIE, "", { ...cookieBase(), maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { ...cookieBase(), maxAge: 0 });
}

/**
 * CSRF defence for cookie-authenticated, state-changing requests: the browser must say the
 * request came from this very site. Cookies are also SameSite=Lax.
 */
export function sameOrigin(req: NextRequest): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).host === (req.headers.get("x-forwarded-host") ?? req.headers.get("host"));
  } catch {
    return false;
  }
}

export function problem(status: number, message: string, errors: string[] = []) {
  return NextResponse.json({ success: false, data: null, message, errors }, { status });
}
