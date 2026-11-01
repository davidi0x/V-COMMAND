import { onlyActive } from "./filters.ts";

export function activeProductCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
