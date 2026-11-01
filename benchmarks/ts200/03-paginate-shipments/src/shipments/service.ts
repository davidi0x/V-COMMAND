import { page } from "./paging.ts";

export function listShipments(ids: number[], p: number): number[] {
  return page(ids, p, 3);
}
