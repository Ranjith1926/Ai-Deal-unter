import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { Nunito_Sans, Rubik } from "next/font/google";
import "./globals.css";
import { CompareProvider, CompareTray } from "@/components/Compare";
import { DemoBanner } from "@/components/DemoBanner";
import { FlashMessage } from "@/components/Flash";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";

// Self-hosted at build time by next/font: no layout shift, no third-party request at runtime.
const heading = Rubik({ subsets: ["latin"], variable: "--font-heading", display: "swap", weight: ["500", "600", "700"] });
const body = Nunito_Sans({ subsets: ["latin"], variable: "--font-body", display: "swap" });

// The header and demo banner depend on the visitor and on live API state, so never prerender.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: "AI Deal Hunter — real deals on Amazon & Flipkart", template: "%s · AI Deal Hunter" },
  description: "Price history, honest deal scores and Amazon vs Flipkart comparison, so you can tell a genuine deal from a fake discount.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: [{ media: "(prefers-color-scheme: light)", color: "#f6fbf8" }, { media: "(prefers-color-scheme: dark)", color: "#07140f" }] };

// Applies the saved theme before first paint to avoid a flash.
const themeScript = `try{var t=localStorage.getItem('theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}catch(e){}`;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // The middleware issues a fresh nonce per request; only scripts carrying it may run (see the CSP there).
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" className={`${heading.variable} ${body.variable}`} suppressHydrationWarning>
      <head><script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-fg">
          Skip to main content
        </a>
        <CompareProvider>
          <FlashMessage />
          <DemoBanner />
          <Header />
          <main id="main" tabIndex={-1} className="container-page min-h-[60dvh] pb-24 pt-6 outline-none">{children}</main>
          <Footer />
          <CompareTray />
        </CompareProvider>
      </body>
    </html>
  );
}
