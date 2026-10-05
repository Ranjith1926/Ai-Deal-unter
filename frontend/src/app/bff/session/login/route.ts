import { NextResponse, type NextRequest } from "next/server";
import { forwardedFor } from "@/lib/clientip";
import { BACKEND, problem, sameOrigin, setAuthCookies } from "@/lib/bff";

export async function POST(req: NextRequest) {
  if (!sameOrigin(req)) return problem(403, "Cross-site request blocked");
  const body = await req.text();
  const res = await fetch(`${BACKEND}/api/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json", ...forwardedFor(req.headers) }, body, cache: "no-store",
  }).catch(() => null);
  if (!res) return problem(503, "The service is unreachable right now");

  const json = await res.json().catch(() => null);
  if (!res.ok || !json?.success) {
    return NextResponse.json(json ?? { success: false, data: null, message: "Sign in failed", errors: [] }, { status: res.status });
  }
  // Tokens go into httpOnly cookies and are never returned to page JavaScript.
  const out = NextResponse.json({ success: true, data: null, message: "Signed in", errors: [] });
  setAuthCookies(out, json.data);
  return out;
}
