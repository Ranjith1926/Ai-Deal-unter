import { NextResponse, type NextRequest } from "next/server";
import { forwardedFor } from "@/lib/clientip";

const BASE = process.env.INTERNAL_API_URL ?? "http://localhost:8000";
const ACCESS = "dh_at";
const REFRESH = "dh_rt";
const REFRESH_DAYS = 30;
const PROTECTED = ["/alerts", "/favorites", "/profile", "/admin", "/notifications"];
const IS_PROD = process.env.NODE_ENV === "production";

// Marketplace image hosts (kept in step with next.config.mjs `images.remotePatterns`).
const IMAGE_HOSTS = ["https://m.media-amazon.com", "https://images-na.ssl-images-amazon.com", "https://rukminim2.flixcart.com"];

/** A strict Content-Security-Policy using a fresh nonce per request. Scripts need the nonce; nothing else runs. */
function contentSecurityPolicy(nonce: string): string {
  return [
    "default-src 'self'",
    // 'strict-dynamic': scripts loaded by our nonced scripts are trusted; host allow-lists and inline scripts are not.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${IS_PROD ? "" : " 'unsafe-eval'"}`,
    "style-src 'self' 'unsafe-inline'", // React `style` props; styles cannot run code
    `img-src 'self' data: ${IMAGE_HOSTS.join(" ")}`,
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(IS_PROD ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}

function withSecurityHeaders(req: NextRequest, extra?: { setCookies?: (res: NextResponse) => void }) {
  const nonce = btoa(crypto.randomUUID());
  const csp = contentSecurityPolicy(nonce);
  // Next reads the CSP *request* header to put the nonce on its own scripts; the layout reads x-nonce.
  const headers = new Headers(req.headers);
  headers.set("x-nonce", nonce);
  headers.set("content-security-policy", csp);
  const res = NextResponse.next({ request: { headers } });
  res.headers.set("Content-Security-Policy", csp);
  extra?.setCookies?.(res);
  return res;
}

/**
 * 1. Sends strangers away from account pages with a real HTTP redirect.
 * 2. Renews an expired session: when the access cookie has lapsed but a refresh cookie remains, rotate the pair here
 *    so server components see a valid session on this very request. Tokens only ever live in httpOnly cookies.
 * 3. Applies a per-request, nonce-based Content-Security-Policy.
 */
export async function middleware(req: NextRequest) {
  const refresh = req.cookies.get(REFRESH)?.value;
  const access = req.cookies.get(ACCESS)?.value;

  const path = req.nextUrl.pathname;
  if (!access && !refresh && PROTECTED.some((p) => path === p || path.startsWith(`${p}/`))) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(path)}`;
    return NextResponse.redirect(url);
  }

  if (access || !refresh) return withSecurityHeaders(req);

  let res: Response;
  try {
    res = await fetch(`${BASE}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...forwardedFor(req.headers) },
      body: JSON.stringify({ refresh_token: refresh }),
    });
  } catch {
    return withSecurityHeaders(req); // backend unreachable: carry on signed out
  }
  // On failure, leave cookies alone: a parallel request may already have rotated them.
  if (!res.ok) return withSecurityHeaders(req);

  const { data } = (await res.json()) as { data: { access_token: string; refresh_token: string; expires_in: number } };
  req.cookies.set(ACCESS, data.access_token);
  req.cookies.set(REFRESH, data.refresh_token);
  const secure = process.env.COOKIE_SECURE === "true";
  const base = { httpOnly: true, sameSite: "lax" as const, secure, path: "/" };
  return withSecurityHeaders(req, {
    setCookies: (out) => {
      out.cookies.set(ACCESS, data.access_token, { ...base, maxAge: data.expires_in });
      out.cookies.set(REFRESH, data.refresh_token, { ...base, maxAge: REFRESH_DAYS * 86400 });
    },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg|.*\\.(?:png|jpg|svg|webp|ico)$).*)"],
};
