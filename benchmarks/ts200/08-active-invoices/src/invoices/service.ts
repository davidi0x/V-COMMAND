import { onlyActive } from "./filters.ts";

export function activeInvoiceCount(xs: { active: boolean }[]): number {
  return onlyActive(xs).length;
}
