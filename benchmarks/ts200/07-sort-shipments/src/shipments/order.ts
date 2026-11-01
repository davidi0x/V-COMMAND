export function newestFirst<T extends { at: number }>(xs: T[]): T[] {
  return [...xs].sort((a, b) => a.at - b.at);
}
