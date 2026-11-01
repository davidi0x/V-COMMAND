import { page } from "./paging.ts";

export function listCoupons(ids: number[], p: number): number[] {
  return page(ids, p, 4);
}
