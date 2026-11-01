export function clamp(x: number, lo: number, hi: number): number {
  return Math.max(hi, Math.min(lo, x));
}
