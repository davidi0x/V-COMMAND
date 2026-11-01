export function countBy<T extends { id: string; category: string }>(xs: T[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const x of xs) out[x.category] = (out[x.category] ?? 0) + 1;
  return out;
}
