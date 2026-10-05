"use client";

import { Check, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { adminCall, errorText, StatusLine } from "./AdminControls";
import { flashAndReload } from "./Flash";
import type { AdminCategory, AdminProduct } from "@/lib/types";

export function CategoryManager({ categories }: { categories: AdminCategory[] }) {
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);

  async function act(fn: () => Promise<{ ok: boolean; json: any; status: number }>, success: string) {
    setBusy(true); setState(null);
    const r = await fn();
    if (r.ok) { flashAndReload(success); return; }
    setBusy(false);
    setState({ ok: false, text: errorText(r) });
  }

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const parent = String(f.get("parent") ?? "");
    await act(() => adminCall("POST", "categories", { name: f.get("name"), parent_id: parent ? Number(parent) : null }), "Category added.");
  }

  async function rename(e: FormEvent<HTMLFormElement>, id: number) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await act(() => adminCall("PATCH", `categories/${id}`, { name: f.get("name"), slug: f.get("slug") }), "Category updated.");
  }

  return (
    <div className="space-y-4">
      <div className="relative overflow-x-auto rounded-2xl border border-line bg-surface">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <caption className="sr-only">Categories</caption>
          <thead className="bg-surface-2"><tr><th scope="col" className="px-3 py-2">Name</th><th scope="col" className="px-3 py-2">Slug</th><th scope="col" className="px-3 py-2">Parent</th><th scope="col" className="px-3 py-2 text-right">Products</th><th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {categories.map((c) => (
              <tr key={c.id} className="border-t border-line align-middle">
                {editing === c.id ? (
                  <td colSpan={4} className="px-3 py-2">
                    <form onSubmit={(e) => rename(e, c.id)} className="flex flex-wrap items-end gap-2">
                      <div><label htmlFor={`n-${c.id}`} className="label">Name</label><input id={`n-${c.id}`} name="name" defaultValue={c.name} required className="input" /></div>
                      <div><label htmlFor={`s-${c.id}`} className="label">Slug</label><input id={`s-${c.id}`} name="slug" defaultValue={c.slug} required className="input" /></div>
                      <button type="submit" disabled={busy} className="btn btn-primary btn-sm"><Check size={16} aria-hidden="true" /> Save</button>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}><X size={16} aria-hidden="true" /> Cancel</button>
                    </form>
                  </td>
                ) : (
                  <>
                    <th scope="row" className="px-3 py-2 font-semibold">{c.name}</th>
                    <td className="px-3 py-2 text-muted">{c.slug}</td>
                    <td className="px-3 py-2 text-muted">{categories.find((p) => p.id === c.parent_id)?.name ?? "—"}</td>
                    <td className="px-3 py-2 text-right tabular">{c.product_count}</td>
                  </>
                )}
                <td className="px-3 py-2 text-right">
                  {editing !== c.id && (
                    <div className="flex justify-end gap-1">
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(c.id)}><Pencil size={16} aria-hidden="true" /> Edit<span className="sr-only"> {c.name}</span></button>
                      {confirming === c.id ? (
                        <button type="button" disabled={busy} className="btn btn-sm bg-danger text-primary-fg" onClick={() => act(() => adminCall("DELETE", `categories/${c.id}`), "Category deleted.")}>
                          <Trash2 size={16} aria-hidden="true" /> Confirm delete<span className="sr-only"> {c.name}</span>
                        </button>
                      ) : (
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirming(c.id)}><Trash2 size={16} aria-hidden="true" /> Delete<span className="sr-only"> {c.name}</span></button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {categories.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-muted">No categories yet. They are created automatically when products are discovered.</td></tr>}
          </tbody>
        </table>
      </div>

      <form onSubmit={add} className="flex flex-wrap items-end gap-2">
        <div><label htmlFor="cat-name" className="label">New category</label><input id="cat-name" name="name" required maxLength={120} className="input" placeholder="e.g. Cameras" /></div>
        <div>
          <label htmlFor="cat-parent" className="label">Parent (optional)</label>
          <select id="cat-parent" name="parent" className="input" defaultValue=""><option value="">None</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
        </div>
        <button type="submit" disabled={busy} className="btn btn-primary">{busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />} Add</button>
      </form>
      <StatusLine state={state} />
    </div>
  );
}

export function ProductActiveToggle({ product }: { product: AdminProduct }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  async function flip() {
    setBusy(true);
    const r = await adminCall("PATCH", `products/${product.id}`, { is_active: !product.is_active });
    if (r.ok) { flashAndReload(`${product.name} ${product.is_active ? "hidden from" : "shown on"} the site.`); return; }
    setBusy(false);
    setMsg(errorText(r));
  }
  return (
    <>
      <button type="button" role="switch" aria-checked={product.is_active} disabled={busy} onClick={flip} className={`btn btn-sm ${product.is_active ? "btn-outline" : "btn-primary"}`}>
        {product.is_active ? "Hide" : "Show"}<span className="sr-only"> {product.name} on the site</span>
      </button>
      <span role="status" className="sr-only">{msg}</span>
    </>
  );
}

export function ListingToggle({ listingId, active, label }: { listingId: number; active: boolean; label: string }) {
  const [busy, setBusy] = useState(false);
  async function flip() {
    setBusy(true);
    const r = await adminCall("PATCH", `listings/${listingId}`, { is_active: !active });
    if (r.ok) { flashAndReload(`${label} listing ${active ? "paused" : "tracked again"}.`); return; }
    setBusy(false);
  }
  return (
    <button type="button" role="switch" aria-checked={active} aria-label={`Track ${label}`} disabled={busy} onClick={flip} className={`chip ${active ? "" : "opacity-60"}`}>
      {label}: {active ? "tracked" : "paused"}
    </button>
  );
}
