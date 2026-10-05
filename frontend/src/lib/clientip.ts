/**
 * Pass the caller's address on to the API. The reverse proxy in front of this app sets X-Forwarded-For
 * (replacing anything the client sent), so forwarding it verbatim lets the API's rate limits and login
 * throttling work per user instead of treating every visitor as this server.
 */
export function forwardedFor(h: { get(name: string): string | null }): Record<string, string> {
  const value = h.get("x-forwarded-for");
  return value ? { "X-Forwarded-For": value } : {};
}
