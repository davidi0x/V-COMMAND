export function onlyActive<T extends { active: boolean }>(xs: T[]): T[] {
  return xs.filter((x) => !x.active);
}
