import { page } from "./paging.ts";

export function listTickets(ids: number[], p: number): number[] {
  return page(ids, p, 4);
}
