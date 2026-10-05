import { NextResponse, type NextRequest } from "next/server";
import { REFRESH_COOKIE } from "@/lib/api";
import { forwardedFor } from "@/lib/clientip";
import { BACKEND, clearAuthCookies, problem, sameOrigin } from "@/lib/bff";

export async function POST(req: NextRequest) {
  if (!sameOrigin(req)) return problem(403, "Cross-site request blocked");
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  if (refresh) {
    // Revoke server-side; failure must not stop the local sign-out.
    await fetch(`${BACKEND}/api/auth/logout`, {
      method: "POST", headers: { "Content-Type": "application/json", ...forwardedFor(req.headers) },
      body: JSON.stringify({ refresh_token: refresh }), cache: "no-store",
    }).catch(() => null);
  }
  const out = NextResponse.json({ success: true, data: null, message: "Signed out", errors: [] });
  clearAuthCookies(out);
  return out;
}
