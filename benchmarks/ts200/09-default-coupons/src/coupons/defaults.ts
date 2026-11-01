export function orDefault(v: number | undefined, fallback: number): number {
  return v || fallback;
}
