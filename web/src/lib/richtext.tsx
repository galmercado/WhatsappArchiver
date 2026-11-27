import type { ReactNode } from "react";

/**
 * Message text → React nodes. Everything is emitted as React text nodes or whitelisted elements,
 * so hostile message bodies (<script>, <img onerror>, javascript: URLs) can never execute.
 */

const URL_RE = /\bhttps?:\/\/[^\s<>"'`]+/gi;
const TRAILING = /[).,;:!?\]}'"]+$/;
const FORMAT_RE = /(\*[^\s*][^*\n]*?\*|_[^\s_][^_\n]*?_|~[^\s~][^~\n]*?~|`[^`\n]+`)/;

export function safeHref(raw: string): string | null {
  try {
    const u = new URL(raw);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function highlight(text: string, terms: readonly string[], key: string): ReactNode {
  const clean = terms.filter((t) => t.length > 0);
  if (clean.length === 0) return text;
  // eslint-disable-next-line security/detect-non-literal-regexp -- every term is regex-escaped
  const re = new RegExp(`(${clean.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(re);
  if (parts.length === 1) return text;
  return parts.map((p, i) =>
    i % 2 === 1 ? (
      <mark key={`${key}-${i}`} className="hit">
        {p}
      </mark>
    ) : (
      p
    ),
  );
}

function linkify(text: string, terms: readonly string[], key: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(URL_RE)) {
    const idx = m.index;
    let url = m[0];
    const trail = TRAILING.exec(url);
    if (trail) url = url.slice(0, url.length - trail[0].length);
    if (idx > last) out.push(highlight(text.slice(last, idx), terms, `${key}t${n}`));
    const href = safeHref(url);
    out.push(
      href ? (
        <a key={`${key}a${n}`} href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-[color:var(--link)] hover:underline">
          {highlight(url, terms, `${key}u${n}`)}
        </a>
      ) : (
        url
      ),
    );
    last = idx + url.length;
    n++;
  }
  if (last < text.length) out.push(highlight(text.slice(last), terms, `${key}e`));
  return out;
}

function boundaryOk(before: string | undefined, after: string | undefined): boolean {
  const w = /[\p{L}\p{N}]/u;
  return !(before && w.test(before)) && !(after && w.test(after));
}

function inline(text: string, terms: readonly string[], key: string, depth = 0): ReactNode[] {
  if (depth > 3) return linkify(text, terms, key);
  const out: ReactNode[] = [];
  let rest = text;
  let consumed = "";
  let n = 0;
  while (rest) {
    const m = FORMAT_RE.exec(rest);
    if (!m) {
      out.push(...linkify(rest, terms, `${key}r${n}`));
      break;
    }
    const tok = m[0];
    const before = (consumed + rest.slice(0, m.index)).slice(-1);
    const after = rest[m.index + tok.length];
    if (!boundaryOk(before || undefined, after)) {
      const upto = rest.slice(0, m.index + 1);
      out.push(...linkify(upto, terms, `${key}x${n}`));
      consumed += upto;
      rest = rest.slice(m.index + 1);
      n++;
      continue;
    }
    if (m.index > 0) out.push(...linkify(rest.slice(0, m.index), terms, `${key}p${n}`));
    const inner = tok.slice(1, -1);
    const k = `${key}f${n}`;
    switch (tok[0]) {
      case "*": out.push(<strong key={k}>{inline(inner, terms, k, depth + 1)}</strong>); break;
      case "_": out.push(<em key={k}>{inline(inner, terms, k, depth + 1)}</em>); break;
      case "~": out.push(<s key={k}>{inline(inner, terms, k, depth + 1)}</s>); break;
      default:
        out.push(<code key={k} className="font-mono text-[13px]">{highlight(inner, terms, k)}</code>);
    }
    consumed += rest.slice(0, m.index + tok.length);
    rest = rest.slice(m.index + tok.length);
    n++;
  }
  return out;
}

export function renderRich(text: string, terms: readonly string[] = []): ReactNode {
  return inline(text, terms, "r");
}

const EMOJI_ONLY = /^(?:\p{Extended_Pictographic}|\p{Emoji_Modifier}|‍|️|\s)+$/u;

/** 1–3 emoji and nothing else → WhatsApp shows them large without extra chrome. */
export function emojiOnlyCount(text: string): number {
  const t = text.trim();
  if (!t || !EMOJI_ONLY.test(t)) return 0;
  if (typeof Intl.Segmenter === "function") {
    return [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(t)].filter((s) => s.segment.trim()).length;
  }
  return Array.from(t).length;
}
