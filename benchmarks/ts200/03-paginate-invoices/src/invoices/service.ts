import { page } from "./paging.ts";

export function listInvoices(ids: number[], p: number): number[] {
  return page(ids, p, 3);
}
