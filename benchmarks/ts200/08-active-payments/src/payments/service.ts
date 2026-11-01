import { onlyActive } from "./filters.ts";

export function activePaymentCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
