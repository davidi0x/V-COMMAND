import { onlyActive } from "./filters.ts";

export function activeOrderCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
