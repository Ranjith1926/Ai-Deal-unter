import Link from "next/link";
import type { ReactNode } from "react";

/**
 * A deliberately tiny Markdown subset for assistant replies: paragraphs, "-" / "1." lists,
 * **bold** and [text](/relative/link). Everything else renders as plain text, and nothing is
 * ever injected as HTML, so model output cannot add markup or external links.
 */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\[[^\]]+\]\(\/[^)\s]*\)|\/deals\/\d+)/g;
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("[")) {
      const [, label, href] = /\[([^\]]+)\]\((\/[^)\s]*)\)/.exec(tok)!;
      out.push(<Link key={key} href={href} className="font-semibold text-primary underline underline-offset-4">{label}</Link>);
    } else out.push(<Link key={key} href={tok} className="font-semibold text-primary underline underline-offset-4">{tok}</Link>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/);
  return (
    <div className="space-y-3">
      {blocks.map((block, bi) => {
        const lines = block.split("\n").filter((l) => l.trim());
        const bullets = lines.every((l) => /^\s*[-*•]\s+/.test(l));
        const numbered = lines.every((l) => /^\s*\d+[.)]\s+/.test(l));
        if (lines.length && (bullets || numbered)) {
          const Tag = numbered ? "ol" : "ul";
          return (
            <Tag key={bi} className={`space-y-1 pl-5 ${numbered ? "list-decimal" : "list-disc"}`}>
              {lines.map((l, li) => <li key={li}>{inline(l.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, ""), `${bi}-${li}`)}</li>)}
            </Tag>
          );
        }
        return <p key={bi}>{lines.map((l, li) => <span key={li}>{li > 0 && <br />}{inline(l, `${bi}-${li}`)}</span>)}</p>;
      })}
    </div>
  );
}
