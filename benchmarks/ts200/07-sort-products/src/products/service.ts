import { newestFirst } from "./order.ts";

export function recentProducts(xs: { id: number; at: number }[]): number[] {
  return newestFirst(xs).map((x) => x.id);
}
