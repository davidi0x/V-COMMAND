import { page } from "./paging.ts";

export function listProducts(ids: number[], p: number): number[] {
  return page(ids, p, 4);
}
