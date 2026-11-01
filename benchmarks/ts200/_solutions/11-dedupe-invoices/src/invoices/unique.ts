export function dedupe<T extends { id: number }>(xs: T[]): T[] {
  const m = new Map<number, T>();
  for (const x of xs) if (!m.has(x.id)) m.set(x.id, x);
  return [...m.values()];
}
