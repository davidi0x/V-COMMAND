import { onlyActive } from "./filters.ts";

export function activeCouponCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
