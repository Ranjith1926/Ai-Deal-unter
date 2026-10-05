"use client";

import { Bot, Loader2, RotateCcw, Send, Sparkles, Wrench } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Markdown } from "./Markdown";

interface Step { tool: string; summary: string; ok: boolean }
interface Msg { role: "user" | "assistant"; content: string; steps?: Step[]; error?: boolean }

const TOOL_LABELS: Record<string, string> = {
  search_products: "Searched products", search_deals: "Searched deals", find_best_deals: "Looked up best deals",
  find_best_value: "Ranked by value", find_products_under_budget: "Checked your budget", find_price_drops: "Checked price drops",
  get_product_details: "Read product details", get_deal_score: "Checked the deal score", get_value_score: "Checked the value score",
  get_historical_low: "Checked the lowest price", get_price_history: "Read price history", compare_prices: "Compared stores",
  compare_products: "Compared products", get_buy_link: "Fetched a buy link", create_price_alert: "Created a price alert",
  get_price_alerts: "Read your alerts", delete_price_alert: "Deleted a price alert", get_system_status: "Checked system status",
};

export const SUGGESTIONS = [
  "Find me the best laptop under ₹60,000.",
  "Which is the best iPhone deal today?",
  "Show me products with a deal score above 80 under ₹20,000.",
  "Find the biggest price drops today.",
  "Compare Amazon and Flipkart prices for the Samsung TV.",
  "Which product has the best value for programming?",
];

export function AssistantChat({ initialQuestion, productId, productName }: { initialQuestion?: string; productId?: number; productName?: string }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState(initialQuestion ?? "");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [announce, setAnnounce] = useState("");

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "end" }); }, [messages, busy]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const next: Msg[] = [...messages, { role: "user", content: question }];
    setMessages(next); setInput(""); setBusy(true); setAnnounce("The assistant is thinking");
    try {
      // Only the plain conversation is sent back; tool results never leave the server.
      const payload = next.filter((m) => !m.error).slice(-18).map(({ role, content }) => ({ role, content }));
      const res = await fetch("/bff/assistant/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: payload, product_id: productId ?? null }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body?.data) {
        const msg = res.status === 429 ? "You've reached the hourly limit for assistant questions. Please try again a little later."
          : res.status === 401 ? "Your session has expired. Please sign in again."
          : body?.errors?.[0] ?? body?.message ?? "Something went wrong. Please try again.";
        setMessages([...next, { role: "assistant", content: msg, error: true }]); setAnnounce(msg);
      } else {
        setMessages([...next, { role: "assistant", content: body.data.reply, steps: body.data.steps }]);
        setAnnounce("The assistant has replied");
      }
    } catch {
      setMessages([...next, { role: "assistant", content: "I couldn't reach the server. Check your connection and try again.", error: true }]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function onSubmit(e: FormEvent) { e.preventDefault(); void send(input); }
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); }
  }

  return (
    <div className="flex flex-col gap-4">
      {productId && productName && (
        <p className="rounded-xl bg-surface-2 px-4 py-2 text-sm">Asking about: <strong className="wrap-anywhere">{productName}</strong></p>
      )}

      <div className="card min-h-72 p-4 md:p-5" role="log" aria-label="Conversation" aria-live="off">
        {messages.length === 0 && (
          <div className="space-y-4">
            <p className="flex items-center gap-2 font-bold"><Sparkles size={18} className="text-primary" aria-hidden="true" /> Ask me anything about deals</p>
            <p className="text-muted">I look up real prices and price history for you, compare Amazon and Flipkart, and tell you honestly whether a discount is genuine.</p>
            <ul className="flex flex-wrap gap-2" aria-label="Suggested questions">
              {SUGGESTIONS.map((s) => <li key={s}><button type="button" className="chip text-left" onClick={() => void send(s)}>{s}</button></li>)}
            </ul>
          </div>
        )}

        <ol className="space-y-5">
          {messages.map((m, i) => (
            <li key={i} className={m.role === "user" ? "flex justify-end" : "flex gap-3"}>
              {m.role === "assistant" && <span className="mt-1 grid size-8 shrink-0 place-items-center rounded-full bg-primary-soft text-primary"><Bot size={18} aria-hidden="true" /></span>}
              <div className={m.role === "user" ? "max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2 text-primary-fg" : "min-w-0 max-w-[92%]"}>
                <p className="sr-only">{m.role === "user" ? "You said:" : "Assistant said:"}</p>
                {m.role === "user" ? <p className="wrap-anywhere whitespace-pre-wrap">{m.content}</p> : (
                  <div className={m.error ? "text-danger" : ""}><Markdown text={m.content} /></div>
                )}
                {m.steps && m.steps.length > 0 && (
                  <details className="mt-2 text-sm text-muted">
                    <summary className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 font-semibold"><Wrench size={14} aria-hidden="true" /> How I found this ({m.steps.length} lookup{m.steps.length === 1 ? "" : "s"})</summary>
                    <ul className="mt-1 space-y-0.5">
                      {m.steps.map((s, si) => <li key={si}>{TOOL_LABELS[s.tool] ?? s.tool}{s.summary && <span className="opacity-80"> — {s.summary}</span>}{!s.ok && <span className="font-semibold"> (didn&apos;t work)</span>}</li>)}
                    </ul>
                  </details>
                )}
              </div>
            </li>
          ))}
          {busy && (
            <li className="flex gap-3" aria-hidden="true">
              <span className="mt-1 grid size-8 shrink-0 place-items-center rounded-full bg-primary-soft text-primary"><Loader2 size={18} className="animate-spin" /></span>
              <div className="space-y-2 pt-1"><div className="skeleton h-4 w-64" /><div className="skeleton h-4 w-48" /></div>
            </li>
          )}
        </ol>
        <div ref={endRef} />
      </div>

      <p role="status" aria-live="polite" className="sr-only">{announce}</p>

      <form onSubmit={onSubmit} className="space-y-2">
        <label htmlFor="assistant-input" className="label">Your question</label>
        <div className="flex items-end gap-2">
          <textarea id="assistant-input" ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey}
            rows={2} maxLength={4000} className="input resize-y" placeholder="e.g. Is this TV actually a good deal?" aria-describedby="assistant-hint" />
          <button type="submit" disabled={busy || !input.trim()} className="btn btn-primary shrink-0" aria-label="Send question">
            {busy ? <Loader2 size={18} className="animate-spin" aria-hidden="true" /> : <Send size={18} aria-hidden="true" />} <span className="hidden sm:inline">Ask</span>
          </button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p id="assistant-hint" className="hint">Enter to send, Shift+Enter for a new line. AI can make mistakes; always confirm the price on the store before buying.</p>
          {messages.length > 0 && <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setMessages([]); setAnnounce("Conversation cleared"); }}><RotateCcw size={14} aria-hidden="true" /> New chat</button>}
        </div>
      </form>
    </div>
  );
}
