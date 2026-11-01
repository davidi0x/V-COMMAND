import { page } from "./paging.ts";

export function listMembers(ids: number[], p: number): number[] {
  return page(ids, p, 2);
}
