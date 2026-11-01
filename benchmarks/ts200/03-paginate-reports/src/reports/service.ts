import { page } from "./paging.ts";

export function listReports(ids: number[], p: number): number[] {
  return page(ids, p, 3);
}
