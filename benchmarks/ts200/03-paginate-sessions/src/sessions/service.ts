import { page } from "./paging.ts";

export function listSessions(ids: number[], p: number): number[] {
  return page(ids, p, 2);
}
