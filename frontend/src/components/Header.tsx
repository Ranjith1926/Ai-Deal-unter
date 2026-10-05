import Link from "next/link";
import { Bell, Heart, Inbox, Menu, Search, Shield, Tag, User as UserIcon } from "lucide-react";
import { LogoutButton } from "./LogoutButton";
import { NavLinks } from "./NavLinks";
import { ThemeToggle } from "./ThemeToggle";
import { getUser } from "@/lib/session";

export async function Header() {
  const user = await getUser();
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
      <div className="container-page flex items-center gap-2 py-2 md:gap-4">
        <Link href="/" className="flex min-h-11 items-center gap-2 font-display text-xl font-bold" aria-label="AI Deal Hunter home">
          <span className="grid size-9 place-items-center rounded-xl bg-primary text-primary-fg"><Tag size={20} aria-hidden="true" /></span>
          <span className="hidden sm:inline">Deal<span className="text-primary">Hunter</span></span>
        </Link>

        <form action="/search" role="search" className="relative mx-1 min-w-0 flex-1 md:max-w-xl">
          <label htmlFor="site-search" className="sr-only">Search products</label>
          <input id="site-search" name="q" type="search" required placeholder="Search phones, laptops, TVs…" className="input pr-12" autoComplete="off" enterKeyHint="search" />
          <button type="submit" className="btn btn-primary btn-icon absolute right-0.5 top-0.5 !min-h-10 !min-w-10 !rounded-lg !p-0" aria-label="Search">
            <Search size={18} aria-hidden="true" />
          </button>
        </form>

        <nav aria-label="Main" className="hidden items-center gap-1 lg:flex"><NavLinks /></nav>

        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <Link href="/alerts" className="btn btn-ghost btn-icon hidden sm:inline-flex" aria-label="Price alerts"><Bell size={20} aria-hidden="true" /></Link>
          <Link href="/favorites" className="btn btn-ghost btn-icon hidden sm:inline-flex" aria-label="Favourites"><Heart size={20} aria-hidden="true" /></Link>
          {user && <Link href="/notifications" className="btn btn-ghost btn-icon hidden sm:inline-flex" aria-label="Notifications"><Inbox size={20} aria-hidden="true" /></Link>}
          {user?.is_admin && <Link href="/admin" className="btn btn-ghost btn-sm hidden md:inline-flex"><Shield size={16} aria-hidden="true" /> Admin</Link>}
          {user ? (
            <Link href="/profile" className="btn btn-outline btn-sm hidden md:inline-flex"><UserIcon size={16} aria-hidden="true" /> {user.name.split(" ")[0]}</Link>
          ) : (
            <Link href="/login" className="btn btn-primary btn-sm hidden md:inline-flex">Sign in</Link>
          )}

          {/* Mobile menu: a native disclosure, so it works without JavaScript. */}
          <details className="group relative lg:hidden">
            <summary className="btn btn-ghost btn-icon list-none [&::-webkit-details-marker]:hidden" aria-label="Menu"><Menu size={22} aria-hidden="true" /></summary>
            <div className="card absolute right-0 top-12 w-64 p-2 shadow-pop">
              <nav aria-label="Mobile" className="flex flex-col"><NavLinks className="min-h-11" /></nav>
              <hr className="my-2 border-line" />
              {user ? (
                <div className="flex flex-col gap-1">
                  <Link href="/profile" className="rounded-lg px-3 py-2 font-semibold hover:bg-surface-2">Profile ({user.name.split(" ")[0]})</Link>
                  <Link href="/notifications" className="rounded-lg px-3 py-2 font-semibold hover:bg-surface-2">Notifications</Link>
                  {user.is_admin && <Link href="/admin" className="rounded-lg px-3 py-2 font-semibold hover:bg-surface-2">Admin</Link>}
                  <LogoutButton className="btn btn-ghost btn-sm justify-start" />
                </div>
              ) : (
                <div className="flex gap-2"><Link href="/login" className="btn btn-primary btn-sm flex-1">Sign in</Link><Link href="/register" className="btn btn-outline btn-sm flex-1">Register</Link></div>
              )}
            </div>
          </details>
        </div>
      </div>
    </header>
  );
}
