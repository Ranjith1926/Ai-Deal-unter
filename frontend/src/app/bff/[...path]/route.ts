import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE } from "@/lib/api";
import { forwardedFor } from "@/lib/clientip";
import { BACKEND, problem, sameOrigin } from "@/lib/bff";

// Token-issuing endpoints are handled by /bff/session/* so tokens never reach page JavaScript.
const BLOCKED = [/^auth\/login$/, /^auth\/refresh$/, /^auth\/logout$/];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = path.join("/");
  if (BLOCKED.some((re) => re.test(target)) || path.some((p) => p === ".." || p === ".")) {
    return problem(404, "Not found");
  }
  const mutating = req.method !== "GET" && req.method !== "HEAD";
  if (mutating && !sameOrigin(req)) return problem(403, "Cross-site request blocked");

  const headers: Record<string, string> = { Accept: "application/json", ...forwardedFor(req.headers) };
  const contentType = req.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;
  const token = req.cookies.get(ACCESS_COOKIE)?.value;
  if (token) headers.Authorization = `Bearer ${token}`;

  const url = new URL(`/api/${target}`, BACKEND);
  url.search = req.nextUrl.search;
  const res = await fetch(url, {
    method: req.method, headers, body: mutating ? await req.text() : undefined, cache: "no-store",
  }).catch(() => null);
  if (!res) return problem(503, "The service is unreachable right now");

  const out = new NextResponse(await res.text(), { status: res.status });
  out.headers.set("Content-Type", res.headers.get("content-type") ?? "application/json");
  out.headers.set("Cache-Control", "no-store");
  const retry = res.headers.get("retry-after");
  if (retry) out.headers.set("Retry-After", retry);
  return out;
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
