import { newestFirst } from "./order.ts";

export function recentReports(xs: { id: number; at: number }[]): number[] {
  return newestFirst(xs).map((x) => x.id);
}
