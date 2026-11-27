/** Deterministic pseudo-waveform (the archive stores no peak data). Heights are 0.15–1. */
export function waveformBars(seed: number, count = 38): number[] {
  let a = (seed * 2654435761) >>> 0;
  const rnd = (): number => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const raw = Array.from({ length: count }, rnd);
  return raw.map((v, i) => {
    const prev = raw[i - 1] ?? v;
    const next = raw[i + 1] ?? v;
    return 0.15 + 0.85 * ((v * 2 + prev + next) / 4);
  });
}
