import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/** Belt and braces next to the ESLint rules: nothing in src/ may inject HTML or evaluate strings. */
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(n) && !/\.test\.tsx?$/.test(n) ? [p] : [];
  });
}

const BANNED = [
  /dangerouslySetInnerHTML/, /\.innerHTML\s*=/, /\.outerHTML\s*=/, /insertAdjacentHTML/, /document\.write/,
  /\beval\s*\(/, /new Function\s*\(/, /setTimeout\(\s*["'`]/, /\bany\b\s*[,;)>=\]]/, /:\s*any\b/,
];

it("source contains no HTML-injection or eval sinks and no `any`", () => {
  const offenders: string[] = [];
  for (const f of files(join(__dirname))) {
    const text = readFileSync(f, "utf8").replace(/\/\/.*$/gm, "");
    for (const re of BANNED) if (re.test(text)) offenders.push(`${f}: ${re}`);
  }
  expect(offenders).toEqual([]);
});

it("no external origins are referenced (CSP default-src 'self')", () => {
  const offenders: string[] = [];
  for (const f of files(join(__dirname))) {
    const text = readFileSync(f, "utf8");
    for (const m of text.matchAll(/https?:\/\/[a-z0-9.-]+/gi)) {
      if (!/example\.com|x\.test|w3\.org|localhost/.test(m[0])) offenders.push(`${f}: ${m[0]}`);
    }
  }
  expect(offenders).toEqual([]);
});
