import { page } from "./paging.ts";

export function listPayments(ids: number[], p: number): number[] {
  return page(ids, p, 2);
}
